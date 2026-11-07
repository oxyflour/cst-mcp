import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { BrepCatalog } from "../src/brep.mjs";

const cube = JSON.parse(fs.readFileSync(new URL("./fixtures/brep_cube.json", import.meta.url), "utf8"));
const hole = JSON.parse(fs.readFileSync(new URL("./fixtures/brep_hole.json", import.meta.url), "utf8"));

function setup(bodies = [structuredClone(cube)]) {
  const catalog = new BrepCatalog();
  catalog.bind("projectA");
  const calls = [];
  const read = async (selector) => {
    calls.push(selector);
    const { names, offset = 0, limit = 50 } = selector;
    const solids = names ? bodies.filter((solid) => names.includes(solid.name)) : bodies.slice(offset, offset + limit);
    return { total: bodies.length, solids: structuredClone(solids) };
  };
  const list = (args = {}) => catalog.listSolids(args, read);
  const ids = (solidId, type, args = {}) => catalog.listEntities({ solidId, type, ...args }, read);
  return { catalog, read, calls, bodies, list, ids };
}

test("solid IDs survive re-listing; pages and targeted reads stay scoped", async () => {
  const other = { ...structuredClone(cube), name: "component1:other" };
  const s = setup([structuredClone(cube), other]);
  const first = await s.list({ limit: 1 });
  assert.equal(first.total, 2);
  assert.equal(first.items.length, 1);
  assert.equal(first.nextOffset, 1);
  const second = await s.list({ offset: 1, limit: 1 });
  assert.notEqual(first.items[0].id, second.items[0].id);
  assert.equal(second.nextOffset, null);
  const solidId = first.items[0].id;
  assert.equal((await s.list({ limit: 1 })).items[0].id, solidId);
  const facePage = await s.ids(solidId, "face", { limit: 2 });
  assert.equal(facePage.total, 6);
  assert.equal(facePage.ids.length, 2);
  assert.equal(facePage.nextOffset, 2);
  assert.deepEqual(s.calls.at(-1), { names: [cube.name] });
  assert.deepEqual((await s.ids(solidId, "face", { offset: 99 })).ids, []);
  assert.ok(!JSON.stringify(facePage).includes("snapshot"));
});

test("every entity's direct links resolve; batches preserve order and duplicates", async () => {
  const s = setup();
  const solidId = (await s.list()).items[0].id;
  const faceId = (await s.ids(solidId, "face")).ids[0];
  const face = await s.catalog.getEntity({ id: faceId }, s.read);
  assert.equal(face.type, "face");
  assert.equal(face.surfaceType, "plane");
  assert.ok(face.firstLoopId.startsWith("loop:"));
  const loop = await s.catalog.getEntity({ id: face.firstLoopId }, s.read);
  assert.equal(loop.faceId, faceId);
  const ce = await s.catalog.getEntity({ id: loop.firstCoedgeId }, s.read);
  const edge = await s.catalog.getEntity({ id: ce.edgeId }, s.read);
  const batch = await s.catalog.getEntities({ ids: [edge.endVertexId, solidId, edge.startVertexId, edge.endVertexId] }, s.read);
  assert.deepEqual(batch.items.map((item) => item.type), ["vertex", "solid", "vertex", "vertex"]);
  assert.deepEqual(batch.items[0], batch.items[3]);
  assert.ok(batch.items[0].position.every(Number.isFinite));
  assert.ok(!("faces" in batch.items[1]));
});

test("changed coordinates reject old IDs; material changes do not", async () => {
  const s = setup();
  const solidId = (await s.list()).items[0].id;
  const faceId = (await s.ids(solidId, "face")).ids[0];
  s.bodies[0].material = "Vacuum";
  assert.equal((await s.catalog.getEntity({ id: faceId }, s.read)).id, faceId);
  s.bodies[0].vertices[0].position[0] += 0.5;
  await assert.rejects(s.catalog.getEntity({ id: faceId }, s.read), { code: "STALE_ENTITY_ID" });
  const fresh = (await s.ids(solidId, "face")).ids[0];
  assert.notEqual(fresh, faceId);
  assert.equal((await s.catalog.getEntity({ id: solidId }, s.read)).material, "Vacuum");
  await assert.rejects(s.catalog.getEntities({ ids: [fresh, faceId] }, s.read), { code: "STALE_ENTITY_ID" });
});

test("deleted solids, project switches, malformed IDs and unsupported relations fail explicitly", async () => {
  const s = setup();
  const solidId = (await s.list()).items[0].id;
  const faceId = (await s.ids(solidId, "face")).ids[0];
  await assert.rejects(s.catalog.getEntity({ id: "face:guess:0:guess" }, s.read), { code: "INVALID_ENTITY_ID" });
  await assert.rejects(s.catalog.adjacency({ id: faceId, relation: "wires" }, s.read), { code: "UNSUPPORTED_RELATION" });
  await assert.rejects(s.catalog.loopBoundary({ loopId: faceId }, s.read), { code: "INVALID_ENTITY_TYPE" });
  await assert.rejects(s.ids(solidId, "vertex", { geometryType: "plane" }), { code: "INVALID_FILTER" });
  s.bodies.pop();
  await assert.rejects(s.catalog.getEntity({ id: faceId }, s.read), { code: "ENTITY_NOT_FOUND" });
  s.catalog.bind("projectB");
  await assert.rejects(s.catalog.getEntity({ id: solidId }, s.read), { code: "INVALID_ENTITY_ID" });
});

test("face, edge and vertex adjacency are reciprocal on a manifold cube", async () => {
  const s = setup();
  const solidId = (await s.list()).items[0].id;
  const faceId = (await s.ids(solidId, "face")).ids[0];
  const adjacent = await s.catalog.adjacency({ id: faceId, relation: "adjacent_faces" }, s.read);
  assert.equal(adjacent.total, 4);
  for (const id of adjacent.ids) {
    assert.ok((await s.catalog.adjacency({ id, relation: "adjacent_faces" }, s.read)).ids.includes(faceId));
  }
  const edgeId = (await s.catalog.adjacency({ id: faceId, relation: "edges" }, s.read)).ids[0];
  assert.equal((await s.catalog.adjacency({ id: edgeId, relation: "faces" }, s.read)).total, 2);
  const vertexId = (await s.catalog.adjacency({ id: edgeId, relation: "vertices" }, s.read)).ids[0];
  assert.equal((await s.catalog.adjacency({ id: vertexId, relation: "edges" }, s.read)).total, 3);
  assert.equal((await s.catalog.adjacency({ id: vertexId, relation: "faces" }, s.read)).total, 3);
});

test("loop boundary pages form one closed oriented ring", async () => {
  const s = setup();
  const solidId = (await s.list()).items[0].id;
  const loopId = (await s.ids(solidId, "loop")).ids[0];
  const first = await s.catalog.loopBoundary({ loopId, limit: 2 }, s.read);
  const last = await s.catalog.loopBoundary({ loopId, offset: first.nextOffset, limit: 2 }, s.read);
  const segments = [...first.items, ...last.items];
  assert.equal(first.total, 4);
  assert.equal(last.nextOffset, null);
  for (let i = 0; i < segments.length; i++) {
    assert.equal(segments[i].endVertexId, segments[(i + 1) % segments.length].startVertexId);
  }
  const ordered = await s.catalog.adjacency({ id: loopId, relation: "coedges" }, s.read);
  assert.equal(ordered.ordered, true);
  assert.deepEqual(ordered.ids, segments.map((segment) => segment.coedgeId));
});

test("through-hole faces keep separate inner loops", async () => {
  const s = setup([structuredClone(hole)]);
  const solidId = (await s.list()).items[0].id;
  const cylinders = await s.ids(solidId, "face", { geometryType: "cone" });
  assert.equal(cylinders.total, 1);
  const loops = await s.catalog.adjacency({ id: cylinders.ids[0], relation: "loops" }, s.read);
  for (const loopId of loops.ids) {
    const edges = await s.catalog.adjacency({ id: loopId, relation: "edges" }, s.read);
    assert.equal(edges.ordered, true);
  }
  const planes = await s.ids(solidId, "face", { geometryType: "plane" });
  const loopCounts = await Promise.all(planes.ids.map(async (id) => (await s.catalog.adjacency({ id, relation: "loops" }, s.read)).total));
  assert.ok(loopCounts.includes(2));
});

test("a periodic seam occurs twice in the ordered boundary, in opposite directions", async () => {
  // Lateral cylinder cut along one seam: lower circle, seam up, upper circle,
  // seam down. The two uses of edge 1 must not be deduplicated.
  const body = structuredClone(cube);
  body.faces = [{ id: 0, shell: 0, firstLoop: 0, next: null, sense: 0, surfaceType: "cone" }];
  body.loops = [{ id: 0, face: 0, firstCoedge: 0, next: null }];
  body.edges = [
    { id: 0, start: 0, end: 0, firstCoedge: 0, sense: 0, curveType: "ellipse" },
    { id: 1, start: 0, end: 1, firstCoedge: 1, sense: 0, curveType: "straight" },
    { id: 2, start: 1, end: 1, firstCoedge: 2, sense: 0, curveType: "ellipse" },
  ];
  body.vertices = body.vertices.slice(0, 2);
  body.coedges = [0, 1, 2, 1].map((edge, i) => ({ id: i, edge, loop: 0, wire: null,
    next: (i + 1) % 4, previous: (i + 3) % 4, partner: i === 1 ? 3 : i === 3 ? 1 : null, sense: i === 3 ? 1 : 0 }));
  for (const key of Object.keys(body.counts)) body.counts[key] = body[key].length;
  const s = setup([body]);
  const solidId = (await s.list()).items[0].id;
  const loopId = (await s.ids(solidId, "loop")).ids[0];
  const edges = await s.catalog.adjacency({ id: loopId, relation: "edges" }, s.read);
  assert.equal(edges.ids.length, 4);
  assert.equal(new Set(edges.ids).size, 3);
  const boundary = await s.catalog.loopBoundary({ loopId }, s.read);
  assert.equal(boundary.items[1].edgeId, boundary.items[3].edgeId);
  assert.equal(boundary.items[1].startVertexId, boundary.items[3].endVertexId);
  assert.equal(boundary.items[1].endVertexId, boundary.items[3].startVertexId);
});
