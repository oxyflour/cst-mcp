"""Offline CSG checks for the skill helper; no CST process or pipe is used."""
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'local_delta', REPO / '.agents/skills/cst-delta-volume/scripts/local_delta.py')
delta = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(delta)
sys.path.insert(0, str(REPO / '.agents/skills/cst-delta-volume/scripts'))
import void_delta
import topology


class IntervalAgent:
    """Independent 1-D CSG model to check operand order and empty-set behavior."""
    def __init__(self, original, modified, before, after, fail=False):
        self.files = {delta.native_path(original): before, delta.native_path(modified): after}
        self.main, self.aux = [(100, 200)], [(300, 400)]
        self.commands, self.fail = [], fail

    def count(self):
        return len(self.main or []) * 6

    def cmd(self, command):
        self.commands.append(command)
        if command == 'ping':
            return 'OK pong'
        if command == 'newbody':
            self.main = None
        elif command == 'swap':
            self.main, self.aux = self.aux, self.main
        elif command.startswith('restore '):
            self.main = list(self.files[command[8:]])
            return 'OK entities=1 faces=' + str(self.count())
        elif command.startswith('prism new '):
            rows = Path(command.split()[-1]).read_text().splitlines()
            xs = [float(row.split()[i]) for row in rows for i in (1, 3)]
            self.main = [(min(xs), max(xs))]
        elif command == 'bool int':
            if self.fail:
                raise RuntimeError('synthetic kernel failure')
            self.main = [(max(a, c), min(b, d)) for a, b in self.main for c, d in self.aux
                         if max(a, c) < min(b, d)]
            self.aux = None
        elif command == 'bool cut':
            for c, d in self.aux:
                result = []
                for a, b in self.main:
                    if b <= c or a >= d:
                        result.append((a, b))
                    else:
                        if a < c:
                            result.append((a, c))
                        if d < b:
                            result.append((d, b))
                self.main = result
            self.aux = None
        elif command == 'faces':
            return 'OK faces=' + str(self.count())
        elif command == 'mass':
            return 'OK volume=%.9g' % sum(b - a for a, b in self.main)
        elif command == 'bbox':
            return 'OK diagnostic interval box'
        elif command.startswith('save main '):
            path = command[10:]
            self.files[path] = list(self.main)
            Path(path).write_text('saved test body', encoding='ascii')
        else:
            raise AssertionError('Unexpected command: ' + command)
        return 'OK'


class LocalDeltaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.original, self.modified = self.root/'original.sat', self.root/'modified.sat'
        self.out = self.root/'output'
        self.bounds = [-1, -1, -1, 4, 1, 1]

    def run_case(self, before, after, fail=False):
        agent = IntervalAgent(self.original, self.modified, before, after, fail)
        report = delta.generate(agent, self.original, self.modified, self.bounds, self.out)
        return agent, report

    def test_translation_produces_distinct_signed_deltas(self):
        agent, report = self.run_case([(0, 2)], [(1, 3)])
        self.assertEqual(agent.files[report['bodies']['remove']['path']], [(0, 1)])
        self.assertEqual(agent.files[report['bodies']['add']['path']], [(2, 3)])
        self.assertEqual(report['status'], 'complete')

    def test_shrink_does_not_export_an_empty_add_body(self):
        _, report = self.run_case([(0, 3)], [(1, 3)])
        self.assertTrue(report['bodies']['add']['empty'])
        self.assertIsNone(report['bodies']['add']['path'])
        self.assertFalse((self.out/'add.sat').exists())

    def test_empty_original_clip_keeps_all_added_material(self):
        agent, report = self.run_case([(-4, -3)], [(0, 1)])
        self.assertTrue(report['bodies']['original_local']['empty'])
        self.assertTrue(report['bodies']['remove']['empty'])
        self.assertEqual(agent.files[report['bodies']['add']['path']], [(0, 1)])

    def test_identical_geometry_has_no_signed_delta(self):
        _, report = self.run_case([(0, 2)], [(0, 2)])
        self.assertTrue(report['bodies']['remove']['empty'])
        self.assertTrue(report['bodies']['add']['empty'])

    def test_kernel_failure_stops_and_preserves_failure_manifest(self):
        agent = IntervalAgent(self.original, self.modified, [(0, 2)], [(1, 3)], fail=True)
        with self.assertRaisesRegex(RuntimeError, 'kernel failure'):
            delta.generate(agent, self.original, self.modified, self.bounds, self.out)
        report = json.loads((self.out/'manifest.json').read_text())
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(agent.commands[-1], 'bool int')
        self.assertFalse((self.out/'remove.sat').exists())

    def test_existing_output_is_not_overwritten_or_sent_to_agent(self):
        self.out.mkdir()
        marker = self.out/'keep.txt'
        marker.write_text('existing', encoding='ascii')
        agent = IntervalAgent(self.original, self.modified, [(0, 2)], [(1, 3)])
        with self.assertRaises(FileExistsError):
            delta.generate(agent, self.original, self.modified, self.bounds, self.out)
        self.assertEqual(marker.read_text(), 'existing')
        self.assertEqual(agent.commands, [])

    def test_invalid_bounds_fail_before_reading_inputs(self):
        for bounds in ([0, 0, 0, 0, 1, 1], [0, 0, 0, 1, math.nan, 1]):
            with self.assertRaises(ValueError):
                delta.validate_inputs(self.original, self.modified, bounds, self.out)

    def test_ascii_protocol_rejects_whitespace_paths(self):
        with self.assertRaisesRegex(ValueError, 'whitespace'):
            delta.native_path(self.root/'a b.sat')

    def test_multi_body_sat_is_rejected_before_pipe_use(self):
        sat = '700 0 2 0\n0 0 0\n1 1e-6 1e-10\nbody $-1 #\nbody $-1 #\nEnd-of-ACIS-data\n'
        self.original.write_text(sat, encoding='ascii')
        self.modified.write_text(sat, encoding='ascii')
        with self.assertRaisesRegex(ValueError, 'exactly one BODY'):
            delta.validate_inputs(self.original, self.modified, self.bounds, self.out)

    def void_case(self, original, old_void, new_void):
        agent = IntervalAgent(self.original, self.modified, original, old_void)
        new_path = self.root/'new_void.sat'
        agent.files[delta.native_path(new_path)] = new_void
        report = void_delta.generate(agent, self.original, self.modified, new_path, self.out)
        removed = [] if report['bodies']['remove']['empty'] else agent.files[report['bodies']['remove']['path']]
        added = [] if report['bodies']['add']['empty'] else agent.files[report['bodies']['add']['path']]
        return agent, report, removed, added

    def test_void_strategy_has_correct_operand_order_and_replay(self):
        original = [(0, 1), (2, 4)]
        _, report, removed, added = self.void_case(original, [(1, 2)], [(.5, 1.5)])
        self.assertEqual(removed, [(.5, 1)])
        self.assertEqual(added, [(1.5, 2)])
        self.assertEqual(report['status'], 'complete')
        inside = lambda intervals, x: any(a < x < b for a, b in intervals)
        for i in range(170):
            x = -.1 + i * .025 + .0125
            replay = (inside(original, x) and not inside(removed, x)) or inside(added, x)
            self.assertEqual(replay, inside([(0, .5), (1.5, 4)], x), x)

    def test_void_strategy_replay_identity_also_exposes_overlapping_fill_tool(self):
        original = [(0, 3)]
        _, _, removed, added = self.void_case(original, [(2, 4)], [(1, 2.5)])
        self.assertEqual(removed, [(1, 2.5)])
        self.assertEqual(added, [(2.5, 4)])
        # The union tool overlaps old material: its volume is not all net addition.
        self.assertTrue(any(a < 2.75 < b for a, b in added))
        inside = lambda intervals, x: any(a < x < b for a, b in intervals)
        for i in range(170):
            x = -.1 + i * .025 + .0125
            replay = (inside(original, x) and not inside(removed, x)) or inside(added, x)
            self.assertEqual(replay, inside([(0, 1), (2.5, 4)], x), x)

    def test_void_strategy_does_not_save_empty_delta(self):
        _, report, removed, added = self.void_case([(0, 1)], [(1, 2)], [(1, 2)])
        self.assertEqual(removed, [])
        self.assertEqual(added, [])
        self.assertTrue(report['bodies']['remove']['empty'])
        self.assertTrue(report['bodies']['add']['empty'])
        self.assertFalse((self.out/'remove.sat').exists())
        self.assertFalse((self.out/'add.sat').exists())

    def test_void_strategy_kernel_failure_stops_before_add(self):
        agent = IntervalAgent(self.original, self.modified, [(0, 1)], [(1, 2)], fail=True)
        new_path = self.root/'new_void.sat'
        agent.files[delta.native_path(new_path)] = [(.5, 1.5)]
        with self.assertRaisesRegex(RuntimeError, 'kernel failure'):
            void_delta.generate(agent, self.original, self.modified, new_path, self.out)
        report = json.loads((self.out/'manifest.json').read_text())
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(agent.commands[-1], 'bool int')
        self.assertNotIn('add', report['bodies'])


class ConePoleTests(unittest.TestCase):
    class Record:
        index = 1
        def __init__(self, kind, point=(0, 0, 1), has_curve=False, paired=False, span=0):
            self.kind, self.has_curve, self.paired = kind, has_curve, paired
            self.f = ['T'] + list(point) + [point[0] + span, point[1], point[2]]
        def ptr(self, at):
            if self.kind == 'coedge':return 2 if self.paired and at == 6 else -1
            return {4: 7, 6: 7, 9: 2 if self.has_curve else -1}.get(at)
        def nums(self, at, count):return self.f[at:at+count]

    class Model:
        faces = [type('Face', (), {'index': 0})()]
        def __init__(self, point=(0, 0, 1), has_curve=False, paired=False, span=0):
            self.edge = ConePoleTests.Record('edge', point, has_curve, span=span)
            self.ce = ConePoleTests.Record('coedge', paired=paired)
        def loops(self, face):return [object()]
        def coedges(self, loop):return [self.ce]
        def rec(self, at):return object() if at is not None and at >= 0 else None
        def edge_of(self, coedge):return self.edge
        def surface(self, face):
            return {'kind':'cone','point':[0,0,0],'axis':[0,0,1],
                    'radius':1,'sine':-math.sqrt(.5),'cosine':math.sqrt(.5)}

    def test_confirmed_cone_apex_is_not_an_open_hole(self):
        report=topology.boundary_report(self.Model())
        self.assertTrue(report['boundary_check_passed'])
        self.assertEqual(len(report['confirmed_degenerate_cone_poles']),1)

    def test_same_endpoint_with_actual_curve_is_not_a_pole(self):
        self.assertFalse(topology.boundary_report(self.Model(has_curve=True))['boundary_check_passed'])

    def test_collapsed_edge_away_from_apex_is_not_waived(self):
        self.assertFalse(topology.boundary_report(self.Model(point=(1,0,1)))['boundary_check_passed'])

    def test_nonzero_length_edge_is_not_waived(self):
        self.assertFalse(topology.boundary_report(self.Model(span=.1))['boundary_check_passed'])


if __name__ == '__main__':
    unittest.main()
