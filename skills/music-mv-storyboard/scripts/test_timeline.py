import copy
import unittest

from timeline import clock, table, validate


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.data = dict(source_start=108, duration=33,
                         cues=[dict(id='L1', start=1, end=10, text='示例', evidence='asr_estimate')],
                         beats=[dict(start=0, end=14, shot='S1', cue_ids=['L1'], action='看向远方', camera='跟随'),
                                dict(start=14, end=33, shot='S1', cue_ids=[], action='延续', camera='保持')],
                         parts=[dict(name='A', start=0, end=14), dict(name='B', start=14, end=33)])

    def test_valid_and_dual_clock(self):
        validate(self.data)
        self.assertIn('01:48.000–02:02.000', table(self.data))
        self.assertEqual(clock(59.9998), '01:00.000')

    def test_gap_overlap_and_truncation(self):
        for key in ('beats', 'parts'):
            for start in (13, 15):
                data = copy.deepcopy(self.data)
                data[key][1]['start'] = start
                with self.subTest(key=key, start=start), self.assertRaises(ValueError):
                    validate(data)
            data = copy.deepcopy(self.data)
            data[key][-1]['end'] = 32
            with self.assertRaises(ValueError):
                validate(data)

    def test_invalid_numbers(self):
        for value in (float('nan'), float('inf'), True, -1):
            data = copy.deepcopy(self.data)
            data['source_start'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate(data)

    def test_unrelated_or_missing_cue(self):
        for cue_ids in (['unknown'], ['L1']):
            data = copy.deepcopy(self.data)
            data['beats'][1]['cue_ids'] = cue_ids
            with self.assertRaises(ValueError):
                validate(data)
        self.data['beats'][0]['cue_ids'] = []
        with self.assertRaises(ValueError):
            validate(self.data)

    def test_bad_cue_evidence_and_duplicate_ids(self):
        data = copy.deepcopy(self.data)
        data['cues'][0]['evidence'] = 'precise_because_decimal'
        with self.assertRaises(ValueError):
            validate(data)
        self.data['cues'].append(copy.deepcopy(self.data['cues'][0]))
        with self.assertRaises(ValueError):
            validate(self.data)

    def test_part_duration_cap(self):
        validate(self.data, 19)
        with self.assertRaises(ValueError):
            validate(self.data, 15)
        self.data['parts'] = [dict(name=str(i), start=s, end=e)
                              for i, (s, e) in enumerate([(0, 5.5), (5.5, 14), (14, 23), (23, 33)])]
        validate(self.data, 10)
        for cap in (9.99, 0, -1, float('nan'), float('inf'), True):
            with self.subTest(cap=cap), self.assertRaises(ValueError):
                validate(self.data, cap)


if __name__ == '__main__':
    unittest.main()
