/** Bounded, live BRep queries. No native pointer or full topology is cached.
 * Entity IDs are opaque, project-scoped handles. Their MAC binds array indices
 * to the complete topology/coordinate fingerprint, preventing stale-index reuse.
 */
import { createHash, createHmac, randomBytes } from "node:crypto";

export const ENTITY_TYPES = ["lump", "shell", "face", "loop", "coedge", "edge", "vertex", "wire"];
const ARRAYS = Object.fromEntries(ENTITY_TYPES.map((kind) => [kind, kind === "vertex" ? "vertices" : kind === "coedge" ? "coedges" : `${kind}s`]));
const RELATIONS = {
  solid: Object.values(ARRAYS),
  lump: ["shells", "faces", "edges", "vertices"],
  shell: ["faces", "wires"],
  face: ["loops", "coedges", "edges", "vertices", "adjacent_faces"],
  loop: ["coedges", "edges", "vertices"],
  coedge: [],
  edge: ["vertices", "coedges", "faces"],
  vertex: ["edges", "faces"],
  wire: ["coedges", "edges", "vertices"],
};
const TYPE_FOR_ARRAY = Object.fromEntries(Object.entries(ARRAYS).map(([kind, key]) => [key, kind]));
const fail = (code, message) => { throw Object.assign(new Error(message), { code }); };
const unique = (items) => [...new Set(items.filter((item) => item !== null))];

function page(items, offset = 0, limit = 50) {
  return { total: items.length, offset, limit, nextOffset: offset + limit < items.length ? offset + limit : null,
    items: items.slice(offset, offset + limit) };
}

export class BrepCatalog {
  #context;
  #secret = randomBytes(32);
  #byName = new Map();
  #byToken = new Map();

  bind(context) {
    if (context !== this.#context) {
      this.#context = context;
      this.#byName.clear();
      this.#byToken.clear();
    }
  }

  #entry(name) {
    if (!this.#byName.has(name)) {
      const entry = { name, token: randomBytes(16).toString("base64url") };
      this.#byName.set(name, entry);
      this.#byToken.set(entry.token, entry);
    }
    return this.#byName.get(name);
  }

  #load(raw) {
    const { name, material, index, ...topology } = raw;
    return { raw, entry: this.#entry(name), fingerprint: createHash("sha256").update(JSON.stringify(topology)).digest("hex") };
  }

  #tag(loaded, type, index) {
    return createHmac("sha256", this.#secret)
      .update([loaded.entry.token, loaded.fingerprint, type, index].join("\0"))
      .digest("base64url").slice(0, 16);
  }

  #id(loaded, type, index) {
    if (type === "solid") return `solid:${loaded.entry.token}`;
    if (index === null) return null;
    if (!Number.isInteger(index) || !loaded.raw[ARRAYS[type]]?.[index]) {
      return fail("INVALID_TOPOLOGY", `invalid ${type} reference`);
    }
    return `${type}:${loaded.entry.token}:${index.toString(36)}:${this.#tag(loaded, type, index)}`;
  }

  #parse(id) {
    const parts = id.split(":");
    const [type, token, position, tag] = parts;
    const entry = this.#byToken.get(token);
    if (!entry || (type === "solid" ? parts.length !== 2 :
      parts.length !== 4 || !ENTITY_TYPES.includes(type) || !/^[0-9a-z]+$/.test(position) || !/^[A-Za-z0-9_-]{16}$/.test(tag))) {
      return fail("INVALID_ENTITY_ID", "unknown entity ID; list solids again for the active project");
    }
    const index = type === "solid" ? null : Number.parseInt(position, 36);
    if (index !== null && (!Number.isSafeInteger(index) || index.toString(36) !== position)) {
      return fail("INVALID_ENTITY_ID", "invalid entity index");
    }
    return { id, type, entry, index, tag };
  }

  async #resolve(ids, read) {
    const refs = ids.map((id) => this.#parse(id));
    const names = unique(refs.map((ref) => ref.entry.name));
    const result = await read({ names });
    const loaded = new Map(result.solids.map((raw) => [raw.name, this.#load(raw)]));
    return refs.map((ref) => {
      const body = loaded.get(ref.entry.name);
      if (!body) return fail("ENTITY_NOT_FOUND", `solid no longer exists: ${ref.entry.name}`);
      if (ref.type !== "solid" && this.#tag(body, ref.type, ref.index) !== ref.tag) {
        return fail("STALE_ENTITY_ID", "solid topology or coordinates changed; list its entities again");
      }
      if (ref.type !== "solid" && !body.raw[ARRAYS[ref.type]][ref.index]) {
        return fail("STALE_ENTITY_ID", "entity is no longer present");
      }
      return { ...ref, body };
    });
  }

  #record({ type, index, body }) {
    const id = this.#id(body, type, index);
    const solidId = this.#id(body, "solid");
    if (type === "solid") {
      return { id, type, name: body.raw.name, material: body.raw.material, counts: body.raw.counts,
        firstLumpId: this.#id(body, "lump", body.raw.firstLump), firstWireId: this.#id(body, "wire", body.raw.firstWire) };
    }
    const raw = body.raw[ARRAYS[type]][index];
    const result = { id, type, solidId };
    const relation = (field, target, output = `${field}Id`) => { result[output] = this.#id(body, target, raw[field]); };
    switch (type) {
      case "lump": relation("firstShell", "shell"); relation("next", "lump"); break;
      case "shell": relation("lump", "lump"); relation("firstFace", "face"); relation("firstWire", "wire"); relation("next", "shell"); break;
      case "face": relation("shell", "shell"); relation("firstLoop", "loop"); relation("next", "face");
        Object.assign(result, { sense: raw.sense, surfaceType: raw.surfaceType }); break;
      case "loop": relation("face", "face"); relation("firstCoedge", "coedge"); relation("next", "loop"); break;
      case "coedge":
        relation("edge", "edge"); relation("loop", "loop"); relation("wire", "wire");
        for (const field of ["next", "previous", "partner"]) relation(field, "coedge");
        result.sense = raw.sense; break;
      case "edge":
        relation("start", "vertex", "startVertexId"); relation("end", "vertex", "endVertexId"); relation("firstCoedge", "coedge");
        Object.assign(result, { sense: raw.sense, curveType: raw.curveType }); break;
      case "vertex": Object.assign(result, { position: raw.position, localPosition: raw.localPosition, coordinateFrame: "global" }); break;
      case "wire": relation("shell", "shell"); relation("firstCoedge", "coedge"); relation("next", "wire"); break;
    }
    return result;
  }

  async listSolids({ offset = 0, limit = 50 }, read) {
    const result = await read({ offset, limit });
    return { total: result.total, offset, limit, nextOffset: offset + limit < result.total ? offset + limit : null,
      items: result.solids.map((raw) => {
        const body = this.#load(raw);
        return { id: this.#id(body, "solid"), name: raw.name, material: raw.material, counts: raw.counts };
      }) };
  }

  async listEntities({ solidId, type, geometryType, offset = 0, limit = 50 }, read) {
    const [ref] = await this.#resolve([solidId], read);
    if (ref.type !== "solid") return fail("INVALID_ENTITY_TYPE", "solidId must identify a solid");
    if (geometryType && !["face", "edge"].includes(type)) return fail("INVALID_FILTER", "geometryType applies only to faces and edges");
    const items = ref.body.raw[ARRAYS[type]].filter((node) => !geometryType ||
      node[type === "face" ? "surfaceType" : "curveType"] === geometryType).map((node) => node.id);
    const { items: indices, ...pagination } = page(items, offset, limit);
    return { solidId, type, ...pagination, ids: indices.map((index) => this.#id(ref.body, type, index)) };
  }

  async getEntity({ id }, read) {
    const [ref] = await this.#resolve([id], read);
    return this.#record(ref);
  }

  async getEntities({ ids }, read) {
    return { items: (await this.#resolve(ids, read)).map((ref) => this.#record(ref)) };
  }

  #ring(raw, start) {
    const result = [], seen = new Set();
    let at = start;
    while (at !== null && !seen.has(at)) {
      if (!raw.coedges[at]) return fail("INVALID_TOPOLOGY", "coedge chain points outside the solid");
      seen.add(at); result.push(at); at = raw.coedges[at].next;
    }
    if (start !== null && at !== start) return fail("INVALID_TOPOLOGY", "boundary does not close at its start");
    return result;
  }

  #neighbors(ref, relation) {
    const { body, type, index } = ref;
    const raw = body.raw;
    if (!RELATIONS[type].includes(relation)) return fail("UNSUPPORTED_RELATION", `${type} supports: ${RELATIONS[type].join(", ") || "use get_entity for direct links"}`);
    const indices = (items) => items.map((node) => node.id);
    let faces = [], coedges = [], edges = [], values = [], ordered = false;
    if (type === "solid") return { indices: indices(raw[relation]), type: TYPE_FOR_ARRAY[relation], ordered: false };
    if (type === "lump") {
      const shells = new Set(indices(raw.shells.filter((shell) => shell.lump === index)));
      if (relation === "shells") return { indices: [...shells], type: "shell", ordered: false };
      faces = indices(raw.faces.filter((face) => shells.has(face.shell)));
    } else if (type === "shell") {
      if (relation === "wires") return { indices: indices(raw.wires.filter((wire) => wire.shell === index)), type: "wire", ordered: false };
      faces = indices(raw.faces.filter((face) => face.shell === index));
    } else if (type === "face") faces = [index];
    else if (type === "loop" || type === "wire") {
      const start = raw[ARRAYS[type]][index].firstCoedge;
      coedges = this.#ring(raw, start); ordered = true;
    } else if (type === "edge") {
      if (relation === "vertices") return { indices: [raw.edges[index].start, raw.edges[index].end].filter((v) => v !== null), type: "vertex", ordered: true };
      coedges = indices(raw.coedges.filter((ce) => ce.edge === index));
    } else if (type === "vertex") {
      edges = indices(raw.edges.filter((edge) => edge.start === index || edge.end === index));
      if (relation === "edges") return { indices: edges, type: "edge", ordered: false };
      const edgeSet = new Set(edges);
      coedges = indices(raw.coedges.filter((ce) => edgeSet.has(ce.edge)));
    }
    if (["lump", "shell", "face"].includes(type)) {
      if (relation === "faces") return { indices: faces, type: "face", ordered: false };
      const faceSet = new Set(faces);
      const loops = indices(raw.loops.filter((loop) => faceSet.has(loop.face)));
      if (relation === "loops") return { indices: loops, type: "loop", ordered: false };
      coedges = loops.flatMap((loop) => this.#ring(raw, raw.loops[loop].firstCoedge));
    }
    if (relation === "coedges") values = coedges;
    else if (relation === "edges") values = coedges.map((ce) => raw.coedges[ce].edge);
    else if (relation === "vertices") {
      edges = unique(coedges.map((ce) => raw.coedges[ce].edge));
      values = edges.flatMap((edge) => [raw.edges[edge].start, raw.edges[edge].end]); ordered = false;
    } else if (relation === "faces") values = coedges.map((ce) => raw.coedges[ce].loop).filter((lp) => lp !== null).map((lp) => raw.loops[lp].face);
    else if (relation === "adjacent_faces") {
      // Include every coedge on the same edge, including non-manifold fans.
      const edgeSet = new Set(coedges.map((ce) => raw.coedges[ce].edge));
      values = raw.coedges.filter((ce) => edgeSet.has(ce.edge) && ce.loop !== null)
        .map((ce) => raw.loops[ce.loop].face).filter((face) => face !== index);
    }
    return { indices: ordered ? values : unique(values), type: relation === "adjacent_faces" ? "face" : TYPE_FOR_ARRAY[relation], ordered };
  }

  async adjacency({ id, relation, offset = 0, limit = 50 }, read) {
    const [ref] = await this.#resolve([id], read);
    const neighbors = this.#neighbors(ref, relation);
    const { items, ...pagination } = page(neighbors.indices, offset, limit);
    return { id, relation, targetType: neighbors.type, ordered: neighbors.ordered, ...pagination,
      ids: items.map((index) => this.#id(ref.body, neighbors.type, index)) };
  }

  async loopBoundary({ loopId, offset = 0, limit = 20 }, read) {
    const [ref] = await this.#resolve([loopId], read);
    if (ref.type !== "loop") return fail("INVALID_ENTITY_TYPE", "loopId must identify a loop");
    const raw = ref.body.raw, loop = raw.loops[ref.index];
    const ring = this.#ring(raw, loop.firstCoedge);
    const { items, ...pagination } = page(ring, offset, limit);
    return { loopId, faceId: this.#id(ref.body, "face", loop.face), closed: loop.firstCoedge !== null,
      ordered: true, ...pagination, items: items.map((index) => {
        const ce = raw.coedges[index], edge = raw.edges[ce.edge];
        return { coedgeId: this.#id(ref.body, "coedge", index), edgeId: this.#id(ref.body, "edge", ce.edge),
          startVertexId: this.#id(ref.body, "vertex", ce.sense ? edge.end : edge.start),
          endVertexId: this.#id(ref.body, "vertex", ce.sense ? edge.start : edge.end),
          sense: ce.sense, partnerId: this.#id(ref.body, "coedge", ce.partner) };
      }) };
  }
}
