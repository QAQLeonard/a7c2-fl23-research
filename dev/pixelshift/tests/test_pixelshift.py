"""Synthetic RAW contracts and optional original-firmware instruction replays."""
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from raw_group import inspect, validate


def synthetic_raw(order='<', *, group=123, shot=1, count=4, prefixed=False):
    data = bytearray(512)
    data[:8] = (b'II' if order == '<' else b'MM') + struct.pack(order + 'HI', 42, 8)

    def directory(at, entries):
        struct.pack_into(order + 'H', data, at, len(entries))
        for i, entry in enumerate(entries):
            struct.pack_into(order + 'HHII', data, at + 2 + 12 * i, *entry)

    model = b'ILCE-7CM2\0'
    data[48:48 + len(model)] = model
    directory(8, [(272, 2, len(model), 48), (34665, 4, 1, 80)])
    directory(80, [(33434, 5, 1, 160), (33437, 5, 1, 168),
                   (34855, 3, 1, 100), (37500, 7, 128, 200)])
    struct.pack_into(order + 'IIII', data, 160, 1, 125, 28, 10)
    start = 200
    if prefixed:
        data[200:212] = b'SONY DSC \0\0\0'
        start += 12
    directory(start, [(0x202f, 7, 6, 300), (0xb048, 8, 1, 0)])
    struct.pack_into(order + 'IBB', data, 300, group, shot, count)
    return bytes(data)


def rows():
    return [{'file': 'frame' + str(n) + '.ARW', 'model': 'ILCE-7CM2',
             'pixel_shift': {'group_id': 8, 'shot': n, 'count': 4},
             'exposure_fields': {'33434': '01', '33437': '02', '34855': '03'}}
            for n in range(1, 5)]


class RawTests(unittest.TestCase):
    def test_both_byte_orders_and_bare_or_prefixed_makernotes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'source.ARW'
            for order in ('<', '>'):
                for prefixed in (False, True):
                    path.write_bytes(synthetic_raw(order, prefixed=prefixed))
                    actual = inspect(path)
                    self.assertEqual(actual['model'], 'ILCE-7CM2')
                    self.assertEqual(actual['pixel_shift'], {'group_id': 123, 'shot': 1, 'count': 4})

    def test_normal_zero_metadata_is_not_a_shifted_image(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'burst.ARW'
            path.write_bytes(synthetic_raw(group=0, shot=0, count=0))
            self.assertIsNone(inspect(path)['pixel_shift'])

    def test_truncated_payload_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.ARW'
            path.write_bytes(synthetic_raw()[:302])
            with self.assertRaises(ValueError):
                inspect(path)

    def test_unordered_sources_are_sorted_without_claiming_hardware(self):
        data = rows()[::-1]
        report = validate(data)
        self.assertEqual(report['ordered_files'], [f'frame{n}.ARW' for n in range(1, 5)])
        self.assertFalse(report['physical_shift_verified'])
        self.assertFalse(report['composition_verified'])
        self.assertEqual(data, rows()[::-1])

    def test_normal_burst_cannot_pass_by_merely_having_four_files(self):
        data = rows()
        data[0]['pixel_shift'] = None
        with self.assertRaisesRegex(ValueError, 'Ordinary burst'):
            validate(data)

    def test_missing_duplicate_composite_or_sixteen_shot_sources_fail(self):
        for field, value in [('shot', 0), ('shot', 2), ('count', 16), ('group_id', 99)]:
            data = rows()
            data[0]['pixel_shift'][field] = value
            with self.assertRaises(ValueError):
                validate(data)
        with self.assertRaises(ValueError):
            validate(rows()[:3])

    def test_exposure_changes_missing_fields_mixed_models_and_repeated_paths_fail(self):
        cases = []
        data = rows(); data[0]['exposure_fields']['34855'] = 'different'; cases.append(data)
        data = rows(); del data[0]['exposure_fields']['33434']; cases.append(data)
        data = rows(); data[0]['model'] = 'ILCE-7CR'; cases.append(data)
        data = rows(); data[0]['file'] = data[1]['file']; cases.append(data)
        for case in cases:
            with self.assertRaises(ValueError):
                validate(case)


class RemoteDumpTests(unittest.TestCase):
    def test_ranges_and_secondary_lists_do_not_lose_record_boundaries(self):
        from sony_property_dump import parse
        records = [
            struct.pack('<HHBBhhBhhh', 0x5001, 3, 1, 1, 0, -1, 1, -4, 4, 1),
            struct.pack('<HHBBBBBHHBBB', 0xd25f, 2, 1, 2, 0, 1, 2, 0, 3, 1, 3, 4),
            struct.pack('<HHBBBBBHBBB', 0xd23a, 2, 1, 1, 1, 4, 2, 3, 1, 4, 16),
            struct.pack('<HHBBB', 0x5009, 0xffff, 0, 1, 0) + b'\2A\0\0\0\0',
        ]
        data = struct.pack('<II', len(records), 0) + b''.join(records)
        report = parse(data)
        self.assertEqual(report['parsed'], 4)
        self.assertEqual(report['consumed_bytes'], len(data))
        self.assertEqual(report['skipped_bytes'], 0)
        self.assertEqual(report['properties'][0]['range'], dict(minimum=-4, maximum=4, step=1))
        self.assertEqual(report['properties'][1]['secondary_enum'], [1, 3, 4])
        self.assertEqual(report['properties'][3]['current'], 'A')
        self.assertEqual([r['code'] for r in report['pixel_shift_properties_present']], ['0xd23a'])
        self.assertEqual([r['offset'] for r in report['properties']],
                         [8 + sum(map(len, records[:n])) for n in range(4)])

    def test_property_like_bytes_inside_arrays_are_not_new_records(self):
        from sony_property_dump import parse
        header = struct.pack('<IIHHBB', 1, 0, 0x5001, 0x4004, 0, 1)
        values = struct.pack('<IHH', 2, 0xd25f, 0xd239)
        report = parse(header + values + values + b'\0')
        self.assertEqual(report['parsed'], 1)
        self.assertEqual(report['properties'][0]['current'], [0xd25f, 0xd239])
        self.assertEqual(report['pixel_shift_properties_present'], [])

    def test_truncated_ranges_and_unconsumed_bytes_are_reported(self):
        from sony_property_dump import parse
        data = struct.pack('<IIHHBBHHBHHH', 1, 0, 0x5001, 4, 1, 1, 0, 1, 1, 0, 10, 1)
        with self.assertRaisesRegex(ValueError, 'Truncated'):
            parse(data[:-1])
        with self.assertRaisesRegex(ValueError, 'Unconsumed'):
            parse(data + b'\0')


class DisplacementTests(unittest.TestCase):
    def test_independent_analytic_scene_has_expected_fractional_motion(self):
        import numpy as np
        from displacement import translation, square_evidence
        rng = np.random.default_rng(7)
        fy, fx = rng.uniform(-0.3, 0.3, (2, 60))
        phase = rng.uniform(0, 2 * np.pi, 60)
        yy, xx = np.indices((128, 128))

        def scene(y, x):
            return np.sin(2 * np.pi * ((yy[..., None] - y) * fy +
                                       (xx[..., None] - x) * fx) + phase).sum(axis=2)

        reference = scene(0, 0)
        positions = []
        for dy, dx in [(0, 0), (0.5, 0), (0.5, 0.5), (0, 0.5)]:
            measured = translation(reference, scene(dy, dx))
            np.testing.assert_allclose(measured, [-dy, -dx], atol=0.04)
            positions.append(2 * measured)  # green sampling has two-RAW-pixel spacing
        report = square_evidence(positions)
        self.assertTrue(report['consistent_with_one_pixel_square'])
        self.assertFalse(report['physical_actuator_verified'])
        self.assertFalse(report['settling_verified'])

    def test_no_motion_wrong_spacing_and_bad_frame_do_not_pass(self):
        from displacement import square_evidence
        for positions in [[[0, 0]] * 4,
                          [[0, 0], [0, 2], [2, 2], [2, 0]],
                          [[0, 0], [0, 1], [1, 1], [7, 3]]]:
            self.assertFalse(square_evidence(positions)['consistent_with_one_pixel_square'])


FIRMWARE = os.environ.get('A7C2_PIXELSHIFT_FIRMWARE_ROOT')


@unittest.skipUnless(FIRMWARE, 'Needs private C2/A7CR original firmware, never USB')
class NativeTests(unittest.TestCase):
    def setUp(self):
        self.c2 = Path(FIRMWARE) / 'a7c2-2.01/components'
        self.cr = Path(FIRMWARE) / 'a7cr-support/components'

    def test_rtti_and_direct_sequence_wrapper_builder_chain(self):
        from audit import audit
        for directory, expected in [(self.c2, 'ILCE-7CM2'), (self.cr, 'ILCE-7CR')]:
            report = audit(directory)
            self.assertEqual(report['profile']['model'], expected)
            self.assertEqual(report['generic_capture_command'], '0x4036')
            self.assertTrue(report['generic_command_is_not_proof_of_pixel_shift'])

    def test_original_four_sixteen_selection_has_identical_18_cases(self):
        from native_replay import select_sequence
        for mode, count in [(1, 4), (2, 16)]:
            for interval in range(9):
                c2 = select_sequence(self.c2, mode, interval)
                cr = select_sequence(self.cr, mode, interval)
                self.assertEqual(c2, cr)
                self.assertEqual(c2['shots'], count)
                self.assertEqual(c2['interval_native_value'], [500, 1000, 2000, 3000, 4000, 5000, 10000, 15000, 30000][interval])
                self.assertEqual(c2['external_calls_executed'], 0)

    def test_original_generic_packets_have_identical_44_cases(self):
        from native_replay import packet
        for mode in range(11):
            for ident, aux in [(0, 0), (1, 1), (0x12345678, 0x87654321), (0xffffffff, 0xffffffff)]:
                c2 = packet(self.c2, mode, ident, aux)
                cr = packet(self.cr, mode, ident, aux)
                self.assertEqual(c2['packet'], cr['packet'])
                self.assertFalse(c2['send_executed'])
                self.assertEqual(c2['trace_calls_omitted'], 1)

    def test_capture_activation_is_separate_from_trigger_preparation(self):
        from native_replay import capture_packet
        for mode, wire_mode in enumerate((2, 10, 12, 8, 9, 3)):
            for ident, auxiliary in ((0, 0), (1, 1), (0x12345678, 0x87654321),
                                     (0xffffffff, 0xffffffff)):
                a = capture_packet(self.c2, mode, ident, auxiliary)
                b = capture_packet(self.cr, mode, ident, auxiliary)
                self.assertEqual(a['packet'], b['packet'])
                self.assertEqual(a['routing'], 0x90040193)
                self.assertEqual(a['routing'], b['routing'])
                raw = bytes.fromhex(a['packet'])
                self.assertEqual(struct.unpack('<BBHIB3xI', raw),
                                 (5, 0, 0x4038, ident, wire_mode, auxiliary))
                self.assertEqual(a['trace_calls_omitted'], 2)
                self.assertEqual(b['trace_calls_omitted'], 2)
                self.assertFalse(a['send_executed'])
                self.assertFalse(b['send_executed'])
        for directory in (self.c2, self.cr):
            with self.assertRaisesRegex(ValueError, 'bounded instruction/memory model'):
                capture_packet(directory, 6, 0, 0)

    def test_original_trinity_setup_and_cp_assignment_match_20_cases(self):
        from trinity_replay import compare
        cases = compare(self.c2, self.cr)
        self.assertEqual(len(cases), 20)
        for case in cases:
            raw = bytes.fromhex(case['ap']['packet'])
            self.assertEqual(struct.unpack_from('<H', raw, 2)[0], 0x40ee)
            self.assertFalse(case['ap']['send_executed'])
            self.assertEqual(case['ap']['trace_calls_omitted'], 1)
            self.assertEqual(case['cp']['external_calls_executed'], 0)
            self.assertFalse(case['cp']['actuator_executed'])
            if case['input'].get('test'):
                self.assertEqual(raw[8:10], b'\x01\x01')
            elif case['input']['mode']:
                self.assertEqual(raw[8], 1)
                self.assertEqual(raw[9], {1: 4, 2: 16}[case['input']['mode']])
            else:
                self.assertEqual(raw[8:], b'\0' * 4)

    def test_original_cp_metadata_matches_63_cases(self):
        from cp_metadata_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 63)
        for case in report['cases']:
            self.assertFalse(case['target']['physical_frame_produced'])
            self.assertEqual(case['target']['external_calls'], 0)

    def test_original_cp_mode_formation_and_consistency_match_63_cases(self):
        from cp_capture_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 63)
        self.assertFalse(report['physical_shift_verified'])
        self.assertFalse(report['settling_verified'])
        for case in report['cases']:
            self.assertEqual(case['target'], case['reference'])
            self.assertEqual(case['target']['hardware_calls'], 0)
            if case['kind'] == 'selection':
                self.assertTrue(case['target']['configuration_inputs_synthetic'])
                if case['input']['mode'] == 2 and case['input']['flag_d88'] and not case['input']['native_state']:
                    self.assertEqual(case['target']['mode'], 23)
            elif case['input']['mode'] == 23:
                self.assertEqual(case['target']['trinity'], case['input']['trinity'])
                self.assertEqual(case['target']['diagnostic_calls_omitted'], 0)

    def test_native_steady_capture_timer_is_a_delay_request_not_a_position_ack(self):
        from cp_timing_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 8)
        self.assertFalse(report['settling_verified'])
        for case in report['cases']:
            self.assertEqual(case['target'], case['reference'])
            expected = max(1, case['exposure_offset_us'] - 9000) if case['exposure_offset_us'] != 9000 else 0
            self.assertEqual(case['target']['delay_us'], expected)
            self.assertFalse(case['target']['timer_api_executed'])
            self.assertFalse(case['target']['actuator_acknowledgement_verified'])

    def test_original_capability_descriptors_match_52_cases(self):
        from capability_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 52)
        change = report['emulated_one_field_change']
        self.assertEqual(change['before']['slot'], 9)
        self.assertFalse(change['before']['support'])
        self.assertTrue(change['after']['support'])
        self.assertFalse(report['installable'])
        for case in report['cases']:
            self.assertFalse(case['reference']['model_identity_inferred'])
            self.assertEqual(case['target']['external_calls_executed'], 0)

    def test_original_sequence_creation_and_clear_boundaries_match_22_cases(self):
        from lifecycle_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 22)
        self.assertFalse(report['installable'])
        self.assertFalse(report['centering_verified'])
        for case in report['cases']:
            result = case['target']
            if case['kind'] == 'enqueue_gate':
                expected = 'request_allocation' if case['enabled'] else 'returned_without_request'
                self.assertEqual(result['boundary'], expected)
                self.assertFalse(result['allocation_executed'])
                self.assertEqual(result['mutex_calls_omitted'], 2)
            elif case['kind'] == 'creator_request':
                self.assertEqual(result['sequence_id'], 0x4bd)
                self.assertTrue(result['native_manager_verified'])
                self.assertFalse(result['construction_executed'])
            elif case['kind'] == 'clear_packet':
                packet = bytes.fromhex(result['packet'])
                self.assertEqual(struct.unpack_from('<H', packet, 2)[0], 0x40ef)
                self.assertFalse(result['transport_executed'])
            else:
                self.assertEqual(result['callback'], 'TrinityShotEnd')
                self.assertFalse(result['service_executed'])
                self.assertFalse(result['callback_executed'])

    def test_original_cp_dispatcher_handles_ap_mode_packets_in_80_paired_cases(self):
        from cp_dispatch_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 80)
        self.assertFalse(report['camera_io'])
        self.assertFalse(report['installable'])
        for case in report['cases']:
            args, result = case['dispatch_input'], case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual(result['check_executed'], args['source_id'] == 0x80020002)
            self.assertTrue(result['handler_executed'])
            self.assertTrue(result['notification_flag_setter_executed'])
            self.assertEqual(result['parameter_changed_flag'], 1)
            self.assertFalse(result['capture_executed'])

    def test_mode23_callbacks_dispatch_stages_before_child_execution(self):
        from cp_stage_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 19)
        self.assertTrue(report['separate_callback_invocations'])
        for index, count in ((4, 7), (9, 8)):
            rows = [c['target'] for c in report['cases'] if c['index'] == index]
            self.assertEqual([r['child_index'] for r in rows[:count]], list(range(count)))
            self.assertTrue(all(r['rejected'] and r['native_return'] == 5 for r in rows[count:]))
            self.assertTrue(all(not r['child_executed'] and not r['scheduler_executed'] for r in rows))
        self.assertFalse(report['exposure_or_centering_executed'])
        self.assertFalse(report['installable'])

    def test_complete_control_producer_and_explicit_off_preserve_native_semantics(self):
        from cp_control_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 16)
        self.assertEqual(report['paired_frame_steps'], 8)
        for case in report['cases']:
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual(result['additional_native_parameter_ids'], [0xf0028, 0xf0029, 0xf002c])
            self.assertEqual(len(result['shots']), 4)
            for shot in result['shots']:
                self.assertTrue(shot['complete_producer_executed'])
                self.assertFalse(shot['precomputed_vector_supplied'])
            for request in result['post_requests']:
                self.assertEqual(request['vector_raw'], result['shots'][-1]['vector_raw'])
                self.assertTrue(request['trinity_still_enabled'])
                self.assertFalse(request['gpio_executed'])
            self.assertEqual(result['off_next_frame']['trinity'], 0)
            self.assertEqual(result['off_next_frame']['native_vector_mode'], 1)
            self.assertEqual(result['off_next_frame']['vector_raw'], [123456, -654321, 65536])
            self.assertFalse(result['automatic_completion_or_abort_executed'])
        self.assertFalse(report['installable'])

    def test_h8_generated_reply_golden_payloads_reach_original_cp_signed_getters(self):
        from cp_controller_reply_replay import decode_reply
        # Golden payloads from original H8 sampling/encoding, independent register
        # inputs and synthetic post-SIO framing; no host-side checksum repair.
        samples = [
            ('a55a08002301dcfe008000000000000000000000000000000000000000000000000000000000f870',
             [291, -292, -32768]),
            ('a55a0800ff7f0100ffff00000000000000000000000000000000000000000000000000000000068f',
             [32767, 1, -1]),
        ]
        for payload, expected in samples:
            a = decode_reply(self.c2, bytes.fromhex(payload))
            b = decode_reply(self.cr, bytes.fromhex(payload))
            self.assertEqual(a, b)
            self.assertEqual(a['values'], expected)
            self.assertTrue(a['complete_40_byte_copy'])
            self.assertTrue(a['bad_checksum_rejected'])
            self.assertFalse(a['payload_reencoded_by_host'])
            self.assertFalse(a['physical_feedback_verified'])

    def test_original_alternate_formatters_build_first_then_second_packets(self):
        from cp_phase_pair_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 8)
        for case in report['cases']:
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertTrue(result['native_first_then_second_formatters'])
            self.assertTrue(result['host_selected_stage_invocations'])
            for shot in result['shots']:
                first, second = bytes.fromhex(shot['first']), bytes.fromhex(shot['second'])
                self.assertEqual(first[:4], bytes([0x39, 7, 7, 3]))
                self.assertEqual(second[:4], bytes([0x39, 8, 8, 2]))
                for packet in (first, second):
                    self.assertEqual(len(packet), 40)
                    check = 0
                    for word in struct.unpack('<20H', packet):
                        check ^= word
                    self.assertEqual(check, 0xf0f)
                self.assertEqual(list(struct.unpack_from('<3i', second, 4)), shot['vector_raw'])
                self.assertEqual(second[28], shot['trinity'])
        self.assertFalse(report['installable'])

    def test_complete_native_control_producer_feeds_both_formatters_without_replacing_its_vector(self):
        from cp_phase_pair_replay import compare
        report = compare(self.c2, self.cr, full_control=True)
        self.assertEqual(report['paired_cases'], 8)
        for case in report['cases']:
            a = case['target']
            self.assertEqual(a, case['reference'])
            self.assertTrue(a['full_control_producer_executed'])
            self.assertFalse(a['precomputed_vector_supplied'])
            self.assertTrue(all(s['native_vector_and_frame_preserved'] for s in a['shots']))
            expected = ([[0, 0, 0]] * 4 if case['scales'] is None else
                        [[0, 0, 0], [49152, 81920, 0], [49152, 81920, 114688], [0, 0, 114688]])
            self.assertEqual([s['vector_raw'] for s in a['shots']], expected)
            for shot in a['shots']:
                self.assertEqual(list(struct.unpack_from('<3i', bytes.fromhex(shot['second']), 4)),
                                 shot['vector_raw'])
        self.assertFalse(report['physical_shift_verified'])

    def test_native_controller_parameter_queue_carries_source_words_and_updates_its_cache(self):
        from cp_parameter_wire_replay import parameter_packets
        for words in (None, bytes.fromhex('1234fedc89abcdef1357fdb9')):
            a = parameter_packets(self.c2, synthetic_words=words)
            self.assertEqual(a, parameter_packets(self.cr, synthetic_words=words))
            self.assertEqual(a['parameter_id'], 0x170006)
            self.assertTrue(a['native_loader_and_cache_scanner_executed'])
            self.assertTrue(a['source_bytes_preserved_by_emission'])
            self.assertTrue(a['prior_cache_synthetic'])
            self.assertEqual(a['source_words_synthetic'], words is not None)
            for index, row in enumerate(a['packets']):
                packet = bytes.fromhex(row['packet'])
                self.assertEqual(packet[7:10], bytes([6, (0x60, 0x64, 0x6c)[index], 255]))
                if words is not None:
                    self.assertEqual(packet[10:14], words[index * 4:index * 4 + 4])
            self.assertFalse(a['physical_configuration_verified'])

    def test_native_adjustment_arithmetic_supplies_full_vectors_and_retains_invalid_range_behavior(self):
        from cp_scale_calculation_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 10)
        self.assertEqual(report['paired_vector_steps'], 40)
        expected = [([4, 8, 8], 0)] * 3 + [([0, 8, 8], 1), ([4, 0, 8], 1),
                    ([4, 8, 0], 1), ([200, 8, 8], 0), ([0, 26, 26], 1),
                    ([0, 26, 26], 1), ([0, 41, 41], 0)]
        for case, (scales, error) in zip(report['cases'], expected):
            a = case['target']
            self.assertEqual(a, case['reference'])
            result = a['scale_calculation']
            self.assertEqual(result['scale_bytes'], scales)
            self.assertEqual(result['native_error_flag'], error)
            self.assertEqual(result['native_scale_store_offsets'], [0, 1, 2])
            self.assertTrue(result['native_measurement_pointer_binding_executed'])
            self.assertEqual(result['native_diagnostic_record_bytes'], 72)
            self.assertFalse(result['host_assigned_scale_bytes'])
            self.assertFalse(result['notification_executed'])
            self.assertTrue(a['same_ram'])
            self.assertTrue(a['full_native_consumer_and_producer_executed'])
            self.assertTrue(a['native_both_packet_formatters_executed'])
            self.assertEqual([s['vector_raw'] for s in a['shots']], [
                [0, 0, 0], [scales[0] * 16384, scales[1] * 16384, 0],
                [scales[0] * 16384, scales[1] * 16384, scales[2] * 16384],
                [0, 0, scales[2] * 16384]])
            for shot in a['shots']:
                self.assertTrue(shot['native_vector_and_frame_preserved'])
                self.assertEqual(list(struct.unpack_from('<3i', bytes.fromhex(shot['second']), 4)),
                                 shot['vector_raw'])
        self.assertFalse(report['physical_shift_verified'])

    def test_native_group_end_uses_reference_cleanup_and_stops_before_unmodeled_resources(self):
        from cp_group_end_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 14)
        for case in report['cases']:
            args, result = case['input'], case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual(result['next_ordinal'], 0)
            self.assertEqual(result['end_marker'], 1)
            self.assertTrue(result['synthetic_cp_enable_word_unchanged'])
            self.assertEqual(result['void_reference_semaphore_calls_omitted'], [])
            self.assertTrue(result['native_lock_ownership_released'])
            self.assertFalse(result['host_assigned_lock_return_value'])
            self.assertFalse(result['pool_return_executed'])
            self.assertFalse(result['pending_callback_executed'])
            self.assertFalse(result['resource_release_executed'])
            self.assertFalse(result['centering_verified'])
            references = args['references']
            if references == 1:
                self.assertTrue(result['native_constructor_executed'])
                self.assertTrue(result['native_cleanup_started'])
                self.assertEqual(result['reference_count'], 0)
                self.assertTrue(result['group_pointer_retained'])
                self.assertEqual(result['native_empty_resource_cleanup_finished'], not args.get('resource', False))
                self.assertEqual(result['boundary'], 'resource_release' if args.get('resource') else 'pool_return')
            else:
                self.assertFalse(result['native_cleanup_started'])
                self.assertFalse(result['group_pointer_retained'])
                self.assertFalse(result['pending_callback_retained'])
                self.assertEqual(result['reference_count'], 1 if references == 2 else None)
                self.assertEqual(result['boundary'], 'pending_callback' if args['pending_callback'] else 'returned')
        self.assertFalse(report['installable'])

    def test_original_atomic_reference_lock_apis_handle_success_rejection_and_contention(self):
        from cp_native_lock_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 16)
        for case in report['cases']:
            args, result = case['input'], case['target']
            self.assertEqual(result, case['reference'])
            self.assertFalse(result['host_assigned_return_value'])
            self.assertFalse(result['wake_or_cross_core_effect_verified'])
            calls = result['calls']
            if args['kind'] == 'cycle':
                self.assertEqual([c['status'] for c in calls], [0, 0])
                self.assertEqual(calls[0]['owner'], 0x36)
                self.assertEqual(calls[1]['owner'], 0)
                self.assertEqual(result['original_atomic_instructions'], ['ldrex', 'strex'])
                self.assertEqual(result['original_barriers'], ['dmb', 'dmb', 'dsb', 'sev'])
            elif args['kind'] == 'busy':
                self.assertEqual(calls[0]['boundary'], 'wait_for_event')
                self.assertIsNone(calls[0]['status'])
                self.assertEqual(result['original_atomic_instructions'], ['ldrex'])
            else:
                self.assertEqual(calls[0]['status'], args['expected'])
                self.assertEqual(result['original_atomic_instructions'], [])

    def test_original_pool_recycling_requires_actual_list_update_beyond_validator_return(self):
        from cp_pool_recycle_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 12)
        for case in report['cases']:
            args, result = case['input'], case['target']
            self.assertEqual(result, case['reference'])
            valid = args['pointer'] == 'valid'
            recycled = valid and not args.get('masked', False)
            self.assertEqual(result['range_validator_return'], int(valid))
            self.assertEqual(result['actual_list_update'], recycled)
            self.assertEqual(result['free_count'], 2 if recycled else 1)
            self.assertFalse(result['host_assigned_return_value'])
            self.assertFalse(result['complete_pool_return_wrapper_executed'])
            self.assertFalse(result['group_completion_executed'])
            if args.get('masked'):
                self.assertEqual(result['range_validator_return'], 1)
                self.assertEqual(result['checked_lock_status'], -25)
                self.assertEqual(result['recycle_helper_return'], 0)
                self.assertFalse(result['actual_list_update'])

    def test_native_pool_entry_mutex_and_same_task_vfp_save_restore_do_not_need_host_returns(self):
        from cp_native_mutex_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 14)
        statuses = [[0, 0], [0, -41, 0], [-25], [-25], [-25], [-18], [-18],
                    [-41], [-25], [-25], [-18], [-18], [None], [None]]
        for index, case in enumerate(report['cases']):
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual([c['status'] for c in result['calls']], statuses[index])
            self.assertEqual(result['native_scheduler_save_restore_pairs'], int(index < 2))
            self.assertTrue(result['vfp_values_preserved'])
            self.assertFalse(result['host_assigned_api_or_scheduler_return'])
            self.assertFalse(result['host_restored_registers'])
            self.assertFalse(result['task_switch_to_different_task_executed'])
            self.assertFalse(result['wait_enqueue_or_wakeup_executed'])

    def test_complete_native_outer_pool_return_preserves_status_and_actual_recycle_distinction(self):
        from cp_pool_return_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 7)
        acquisitions = [0, 0, 0, -25, -25, -25, None]
        releases = [0, 0, 0, -25, -41, -25, None]
        counts = [1, 2, 0, 0, 1, 1, 0]
        updates = [True, True, False, False, True, True, False]
        for index, case in enumerate(report['cases']):
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual(result['entry_mutex_status'], acquisitions[index])
            self.assertEqual(result['entry_mutex_release_status'], releases[index])
            self.assertEqual(result['node_recycled'], updates[index])
            self.assertEqual(result['free_count'], counts[index])
            self.assertEqual(result['same_task_scheduler_entries'], int(index < 3))
            self.assertEqual(result['complete_outer_pool_function_returned'], index != 6)
            self.assertEqual(result['outer_return'], 0 if index != 6 else None)
            self.assertFalse(result['host_assigned_api_or_scheduler_return'])
            self.assertFalse(result['host_restored_registers'])
            self.assertFalse(result['physical_allocation_deletion_executed'])
            self.assertFalse(result['camera_group_completion_executed'])

    def test_group_end_recycles_final_empty_object_and_detaches_before_pending_callback(self):
        from cp_group_end_replay import compare
        report = compare(self.c2, self.cr, full_pool=True)
        self.assertEqual(report['paired_cases'], 7)
        self.assertTrue(report['full_pool_requested'])
        for case in report['cases']:
            args, result = case['input'], case['target']
            self.assertEqual(result, case['reference'])
            resource = args.get('resource', False)
            recycled = args['references'] == 1 and not resource
            self.assertEqual(result['pool_return_executed'], recycled)
            self.assertEqual(result['whole_pool']['free_count'], int(recycled))
            self.assertEqual(result['whole_pool']['outer_pool_return_status'], 0 if recycled else None)
            self.assertEqual(result['scheduler_executed'], recycled)
            self.assertEqual(result['group_pointer_retained'], resource)
            self.assertEqual(result['boundary'], 'resource_release' if resource else
                             'pending_callback' if args['pending_callback'] else 'returned')
            self.assertFalse(result['pending_callback_executed'])
            self.assertFalse(result['resource_release_executed'])
            self.assertFalse(result['capture_scheduler_executed'])
            self.assertTrue(result['native_lock_ownership_released'])
            self.assertTrue(result['synthetic_cp_enable_word_unchanged'])
        self.assertFalse(report['centering_verified'])

    def test_original_client_records_and_post_dequeue_invocation_register_actual_completion_event(self):
        from cp_completion_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 7)
        bits = [0, 0x204, 0x10000, 0x10204, 0, 0, 0]
        statuses = [[], [], [0], [0], [-25], [-25], []]
        for index, case in enumerate(report['cases']):
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual(result['native_client_categories'], [0, 2])
            self.assertEqual(result['event_id'], 0x35)
            self.assertEqual(result['event_mask'], 0x10000)
            self.assertEqual(result['event_bits'], bits[index])
            self.assertEqual(result['event_statuses'], statuses[index])
            self.assertEqual(result['completion_pending'], index < 2)
            self.assertEqual(result['worker_messages_completed'], 1 if index == 6 else 2)
            self.assertTrue(result['sender_bytes_preserved'])
            self.assertTrue(result['unrelated_start_callback_preserved'])
            self.assertFalse(result['actor_queue_transport_executed'])
            self.assertFalse(result['complete_sender_function_executed'])
            self.assertFalse(result['host_assigned_callback_or_api_return'])
            self.assertFalse(result['waiting_capture_task_woken'])

    def test_group_end_uses_native_registered_callback_after_pool_return_to_set_completion_flag(self):
        from cp_group_end_replay import compare
        report = compare(self.c2, self.cr, native_completion=True)
        self.assertEqual(report['paired_cases'], 4)
        self.assertTrue(report['native_completion_requested'])
        for case in report['cases']:
            args, result = case['input'], case['target']
            self.assertEqual(result, case['reference'])
            resource = args.get('resource', False)
            self.assertEqual(result['pending_callback_executed'], not resource)
            self.assertEqual(result['completion_event_bits'], 0x204 if resource else 0x10204)
            self.assertEqual(result['native_completion']['event_statuses'], [] if resource else [0])
            self.assertEqual(result['native_completion']['event_arguments'], [] if resource else [[0x35, 0x10000]])
            self.assertEqual(result['group_pointer_retained'], resource)
            self.assertEqual(result['pending_callback_retained'], resource)
            self.assertEqual(result['boundary'], 'resource_release' if resource else 'returned')
            self.assertEqual(result['pool_return_executed'], args['references'] == 1 and not resource)
            self.assertTrue(result['native_client_registration']['sender_bytes_preserved'])
            self.assertFalse(result['actor_queue_transport_executed'])
            self.assertFalse(result['waiting_capture_task_woken'])
            self.assertFalse(result['capture_scheduler_executed'])
            self.assertTrue(result['synthetic_cp_enable_word_unchanged'])
        self.assertFalse(report['physical_shift_verified'])

    def test_native_actor_queue_apis_preserve_fifo_wrap_padding_errors_and_wait_boundaries(self):
        from cp_actor_queue_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 12)
        expected = [[0, 0, 28, 28, -50], [0, 0, 28, 28], [0, 0, 0, 1, 5, 13],
                    [0, -50, 28, -50], [-17, -17, -18, -18], [-18, -18, -17],
                    [-25], [-25], [-25], [None], [None], [0]]
        for index, case in enumerate(report['cases']):
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual([op['status'] for op in result['operations']], expected[index])
            self.assertFalse(result['host_copied_payload_into_receiver'])
            self.assertFalse(result['host_assigned_api_return'])
            self.assertFalse(result['waiter_enqueue_or_wakeup_executed'])
            self.assertFalse(result['task_switch_to_different_task_executed'])
        for index, capacity, end in ((0, 128, 64), (1, 64, 52), (2, 128, 36), (3, 32, 0)):
            final = report['cases'][index]['target']['operations'][-1]
            self.assertEqual([final['free_bytes'], final['queued_messages'], final['read_index'], final['write_index']],
                             [capacity, 0, end, end])
        self.assertEqual(sum(report['cases'][1]['target']['original_memcpy_lengths']), 112)
        self.assertEqual(report['cases'][9]['target']['operations'][0]['boundary'], 'receive_wait_transition')
        self.assertEqual(report['cases'][10]['target']['operations'][0]['boundary'], 'wait_for_event')

    def test_complete_native_senders_and_worker_use_actual_queue_bytes_without_receiver_copy(self):
        from cp_actor_delivery_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 6)
        bits = [0, 0x204, 0, 0x204, 0x10204, 0x10204]
        for index, case in enumerate(report['cases']):
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual(result['native_client_categories'], [0, 2])
            self.assertEqual(result['native_send_statuses'], [0, 0])
            self.assertEqual(result['native_receive_statuses'], [28, 28])
            self.assertEqual(result['native_sender_returns'], [1, 1])
            self.assertEqual(result['native_worker_loop_iterations'], 2)
            self.assertEqual(result['profiling_guard_calls'], 2)
            self.assertEqual(result['queue_free_bytes'], 128)
            self.assertEqual(result['queue_messages'], 0)
            self.assertEqual(result['queue_read_index'], (case['input']['start'] + 64) % 128)
            self.assertEqual(result['queue_write_index'], result['queue_read_index'])
            self.assertEqual(result['event_bits'], bits[index])
            self.assertEqual(result['completion_pending'], index < 4)
            self.assertTrue(result['actor_queue_transport_executed'])
            self.assertTrue(result['complete_sender_function_executed'])
            self.assertFalse(result['complete_worker_function_returned'])
            self.assertFalse(result['host_copied_payload_into_receiver'])
            self.assertFalse(result['host_assigned_callback_or_api_return'])
            self.assertFalse(result['cross_task_scheduling_executed'])
            self.assertFalse(result['waiting_capture_task_woken'])

    def test_group_end_source_registration_uses_native_queue_transport_and_preserves_paused_actor(self):
        from cp_group_end_replay import compare
        report = compare(self.c2, self.cr, native_queue=True)
        self.assertEqual(report['paired_cases'], 4)
        self.assertTrue(report['native_queue_requested'])
        for case in report['cases']:
            args, result = case['input'], case['target']
            self.assertEqual(result, case['reference'])
            resource = args.get('resource', False)
            self.assertTrue(result['actor_queue_transport_executed'])
            registration = result['native_client_registration']
            self.assertEqual(registration['native_send_statuses'], [0, 0])
            self.assertEqual(registration['native_receive_statuses'], [28, 28])
            self.assertTrue(registration['sender_bytes_preserved'])
            self.assertFalse(registration['host_copied_payload_into_receiver'])
            self.assertEqual(result['pending_callback_executed'], not resource)
            self.assertEqual(result['completion_event_bits'], 0x204 if resource else 0x10204)
            self.assertEqual(result['group_pointer_retained'], resource)
            self.assertFalse(result['waiting_capture_task_woken'])
            self.assertFalse(result['capture_scheduler_executed'])
        self.assertFalse(report['physical_shift_verified'])

    def test_original_clear_handler_queues_end_for_real_worker_invocation_and_resource_boundary(self):
        from cp_queued_end_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 6)
        for case in report['cases']:
            args, result = case['input'], case['target']
            self.assertEqual(result, case['reference'])
            resource = args.get('resource', False)
            recycled = args.get('references', 1) == 1 and not resource
            self.assertEqual(result['clear_send_status'], 0)
            self.assertEqual(result['complete_sender_return'], 1)
            self.assertEqual(result['clear_handler_return'], 1)
            self.assertEqual(result['clear_receive_length'], 28)
            self.assertEqual(result['native_worker_end_invocations'], 1)
            self.assertEqual(result['clear_worker_message_completed'], not resource)
            self.assertEqual(result['queue_messages'], 0)
            self.assertEqual(result['queue_free_bytes'], 128)
            self.assertEqual(result['queue_index'], (args.get('start', 0) + 96) % 128)
            self.assertEqual(result['object_recycled'], recycled)
            self.assertEqual(result['reference_count'], args.get('references', 1) - 1 if args.get('references', 1) else None)
            self.assertEqual(result['group_pointer_retained'], resource)
            self.assertEqual(result['event_bits'], 0x204 if resource else 0x10204)
            self.assertEqual(result['native_completion']['event_statuses'], [] if resource else [0])
            self.assertTrue(result['queued_clear_record_preserved'])
            self.assertTrue(result['worker_roles_preserved_by_native_callees'])
            self.assertFalse(result['host_restored_gpr_or_fpu_values'])
            self.assertFalse(result['direct_host_group_end_invocation'])
            self.assertFalse(result['ap_to_cp_transport_executed'])
            self.assertFalse(result['waiting_capture_task_woken'])
            self.assertFalse(result['captured_resource_release_executed'])
        self.assertFalse(report['physical_shift_verified'])

    def test_capture_consumer_queries_original_event_and_preserves_priority_and_existing_status(self):
        from cp_completion_consumer_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 9)
        cases = report['cases']
        self.assertEqual([c['target']['frame_status_after'] for c in cases],
                         [0, 8, 0x20, 0x20, 0, 0x60, 0, 0, 0])
        self.assertEqual([c['target']['boundary'] for c in cases[4:]],
                         ['recovery_branch', 'consumer_slice_boundary',
                          'reference_rejected', 'reference_rejected', 'wait_for_event'])
        self.assertEqual([cases[i]['target']['reference_api_status'] for i in (6, 7)], [-25, -25])
        for case in cases:
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertTrue(result['event_query_not_blocking_wait'])
            self.assertFalse(result['host_assigned_event_or_api_result'])
            self.assertFalse(result['actual_waiting_task_woken'])
            self.assertFalse(result['remainder_of_capture_thread_executed'])
            self.assertFalse(result['physical_ready_verified'])
        self.assertEqual(cases[3]['target']['native_status_markers'], [0x20])
        self.assertEqual(cases[4]['target']['native_status_markers'], [])

    def test_queued_end_consumer_observes_same_ram_event_including_unreleased_resource(self):
        from cp_queued_end_replay import compare
        report = compare(self.c2, self.cr, consume_completion=True)
        self.assertEqual(report['paired_cases'], 6)
        self.assertTrue(report['consume_completion_requested'])
        for case in report['cases']:
            result = case['target']
            self.assertEqual(result, case['reference'])
            resource = case['input'].get('resource', False)
            consumer = result['native_event_consumer']
            self.assertEqual(consumer['queried_waiter_and_bits'], [0, 0x204 if resource else 0x10204])
            self.assertEqual(consumer['frame_status_after'], 0 if resource else 0x20)
            self.assertEqual(consumer['native_status_markers'], [] if resource else [0x20])
            self.assertEqual(result['clear_worker_message_completed'], not resource)
            self.assertFalse(consumer['actual_waiting_task_woken'])
            self.assertFalse(consumer['host_assigned_event_or_api_result'])

    def test_poweroff_one_shot_flag_and_explicit_request_construction_boundary(self):
        from cp_poweroff_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 3)
        for case in report['cases']:
            result, initial = case['target'], case['initial']
            self.assertEqual(result, case['reference'])
            self.assertEqual(result['poweroff_detect_flag'], initial or 1)
            self.assertTrue(result['native_poweroff_role_verified'])
            self.assertEqual(result['native_flag_writes'], [[1, 1]] if initial == 0 else [])
            self.assertEqual(result['already_complete_native_return'], initial != 0)
            self.assertEqual(result['post_allocation_buffer_fixture_used'], initial == 0)
            self.assertEqual(result['original_payload'],
                             struct.pack('<4I', 0x920162, 0, 0, 0).hex() if initial == 0 else None)
            self.assertTrue(result['object_end_marker_unchanged'])
            for field in ('allocation_api_executed', 'local_send_executed', 'completion_callback_executed',
                          'host_assigned_allocator_or_send_result', 'actual_poweroff_check_completed',
                          'physical_ready_verified'):
                self.assertFalse(result[field])

    def test_notification_allocator_owns_real_free_list_blocks_without_supplied_pointer(self):
        from cp_poweroff_allocate_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 4)
        self.assertEqual([c['target']['boundary'] for c in report['cases']],
                         ['before_local_send', 'before_local_send', 'allocation_backpressure', 'pool_lock_wait'])
        for index, case in enumerate(report['cases']):
            result = case['target']
            self.assertEqual(result, case['reference'])
            completed = index < 2
            self.assertEqual(result['payload_constructed'], completed)
            self.assertEqual(result['allocated_buffers'], int(completed))
            self.assertEqual(result['original_allocator_return'], 0 if completed else None)
            self.assertEqual(result['original_payload'],
                             struct.pack('<4I', 0x920162, 0, 0, 0).hex() if completed else None)
            self.assertTrue(result['allocation_api_executed'])
            self.assertFalse(result['host_supplied_buffer_pointer_or_api_result'])
            self.assertFalse(result['post_allocation_buffer_fixture_used'])
            self.assertEqual(result['native_core_bookkeeping_word'], 0)
            self.assertEqual(result['native_dispatch_disable_word'], int(index == 3))
            self.assertFalse(result['local_send_executed'])
            self.assertFalse(result['physical_ready_verified'])
        self.assertEqual([c['target']['pool_remaining_bytes'] for c in report['cases']], [128, 0, 0, 256])
        self.assertEqual([c['target']['pool_head_retained'] for c in report['cases']], [True, False, False, True])
        self.assertEqual([c['target']['native_allocated_payload_offset'] for c in report['cases']],
                         [0xc0, 0x40, None, None])

    def test_ap_built_clear_reaches_native_cp_dispatch_worker_and_event_consumer(self):
        from cp_queued_end_replay import compare
        report = compare(self.c2, self.cr, ap_dispatch=True, consume_completion=True)
        self.assertEqual(report['paired_cases'], 6)
        self.assertTrue(report['ap_dispatch_requested'])
        for case in report['cases']:
            result = case['target']
            self.assertEqual(result, case['reference'])
            ap = result['native_ap_dispatch']
            packet = bytes.fromhex(ap['ap_builder']['packet'])
            self.assertEqual(struct.unpack_from('<H', packet, 2)[0], 0x40ef)
            self.assertEqual(ap['ap_builder']['routing'], 0x90030001)
            self.assertEqual(ap['native_handler_entries'], 1)
            self.assertTrue(ap['host_byte_bridge_used'])
            self.assertFalse(ap['hardware_transport_executed'])
            self.assertEqual(result['native_worker_end_invocations'], 1)
            self.assertEqual(result['native_event_consumer']['frame_status_after'],
                             0 if case['input'].get('resource') else 0x20)
            self.assertFalse(result['native_event_consumer']['actual_waiting_task_woken'])

    def test_poweroff_uses_actual_local_cache_listener_and_frees_its_request(self):
        from cp_poweroff_request_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 9)
        self.assertFalse(report['installable'])
        extra_values = (0x81, 0x84, 0x85, 0x94)
        for index, case in enumerate(report['cases']):
            result = case['target']
            self.assertEqual(result, case['reference'])
            available = case['input'].get('descriptor_available', True)
            self.assertEqual(result['listener_registration_status'], 0 if available else -1023)
            self.assertEqual(result['native_send_status'], 0 if available else -1020)
            self.assertEqual(result['native_local_route_entries'], 1)
            self.assertEqual(result['native_task_id'], 1 if available else None)
            self.assertEqual(result['native_free_status'], 0)
            self.assertEqual(result['native_free_calls'], 1)
            self.assertEqual(result['payload_pool_bytes_restored'], 256)
            self.assertEqual(result['payload_live_count'], 0)
            cached = case['input'].get('cache_words', [0, 0, 0, 0])
            self.assertEqual(result['cache_words'], cached)
            self.assertEqual(result['native_reply'],
                             struct.pack('<4I', *(cached if available else [0x920162, 0, 0, 0])).hex())
            extra = available and cached[1] in extra_values
            self.assertEqual(result['boundary'],
                             'before_additional_poweroff_message' if extra else 'before_diagnostics')
            self.assertEqual(result['cached_off_factor'], cached[1] if available else 0)
            self.assertFalse(result['host_supplied_callback_pointer_or_api_return'])
            self.assertFalse(result['additional_poweroff_message_executed'])
            self.assertFalse(result['later_completion_callback_executed'])
            self.assertFalse(result['physical_completion_verified'])
            self.assertFalse(result['full_poweroff_check_executed'])

    def test_native_caif_callback_queues_gpio_action_before_worker_consumes_it(self):
        from cp_caif_gpio_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 8)
        self.assertFalse(report['installable'])
        for case in report['cases']:
            args, result = case['input'], case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual(result['factory_gpio_pairs'], [[11, 26], [11, 25]])
            self.assertEqual(len(result['native_parameter_reads']), 12)
            self.assertEqual(result['omitted_mutex_calls'], 29)
            skip = bool(args.get('skip'))
            direct = bool(args.get('debug'))
            queued = not skip and not direct
            self.assertEqual(result['event_bits_after'], 0x10204)
            self.assertEqual(result['event_bits_before_action'], None if skip else 0x10204)
            self.assertEqual(result['backend_selector'], 0 if direct else 1)
            self.assertEqual(result['mmio_writes'], [] if skip else [[0xf1028048, 4, 1 << (25 if direct else 26)]])
            self.assertEqual(result['mmio_writes_before_delivery'], result['mmio_writes'] if direct else [])
            self.assertEqual(result['native_sdk_receive_and_worker_copy_free_executed'], queued)
            self.assertEqual(result['callback_completed'], skip)
            self.assertEqual(result['omitted_diagnostic_calls'], 1 if skip else 2)
            if queued:
                self.assertEqual(result['queued_record'], result['native_received_record'])
                record = bytes.fromhex(result['queued_record'])
                self.assertEqual(record[0], 0x12)
                self.assertEqual(struct.unpack_from('<II', record, 12), (11, 26))
                self.assertEqual(result['boundary'], 'before_worker_trace')
            else:
                self.assertIsNone(result['queued_record'])
            self.assertEqual(result['request_live_buffers_after'], 0)
            self.assertTrue(result['gpio_data_register_not_mirrored_from_command'])
            self.assertTrue(result['native_selector_postinit_slice_executed'])
            self.assertFalse(result['native_backend_initialization_executed'])
            self.assertFalse(result['host_assigned_api_return_or_copied_queue_data'])
            self.assertFalse(result['full_worker_loop_executed'])
            self.assertFalse(result['physical_gpio_or_sensor_verified'])
            self.assertFalse(result['exposure_sync_verified'])

    def test_dispatched_mode_reaches_current_settings_and_native_tc_input(self):
        from cp_mode_source_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 6)
        for case in report['cases']:
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual(result['copied_settings_mode'], int(result['mode'] != 0))
            self.assertEqual(result['published_trinity_flag'], int(result['mode'] != 0))
            self.assertEqual(result['native_copy_lengths'], [0xd64, 340, 192, 192])
            self.assertTrue(result['native_first_pointer_bound'])
            self.assertFalse(result['host_reassigned_mode'])
            self.assertFalse(result['semaphore_admission_executed'])
            self.assertFalse(result['scheduler_executed'])
            self.assertFalse(result['capture_end_executed'])
        self.assertFalse(report['installable'])

    def test_steady_timer_callback_and_waiter_use_the_same_native_event(self):
        from cp_steady_event_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 8)
        self.assertTrue(report['separate_callback_and_waiter_invocations'])
        for case in report['cases']:
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual((result['event_id'], result['event_mask']), (0x2e, 0x80000000))
            self.assertEqual(result['timeout_argument'], 10000)
            self.assertTrue(result['original_arm_context_detector_executed'])
            self.assertTrue(result['native_predicate_and_inhibitions_verified'])
            self.assertTrue(result['native_bypass_verified'])
            self.assertFalse(result['rtos_event_api_executed'])
            self.assertFalse(result['wait_completed'])
            self.assertFalse(result['motor_settling_verified'])

    def test_alternate_reply_reaches_its_own_decoder_and_signed_getters(self):
        from cp_feedback_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 24)
        shots = report['target']['shots']
        self.assertEqual(len(shots), 4)
        for ordinal, shot in enumerate(shots):
            self.assertFalse(shot['settling_verified'])
            self.assertFalse(shot['physical_units_verified'])
            self.assertEqual(len(shot['cases']), 6)
            for case in shot['cases']:
                self.assertEqual(case['signed_values'], [-17 - ordinal, 31 + ordinal, -5])
                self.assertEqual(case['native_history_copy_bytes'], 16)
                self.assertEqual(case['next_index'], 1 if case['initial_index'] == 0 else 0)
                self.assertEqual(case['history_source'], 'previous_entry'
                                 if case['source_kind'] == 1 else 'context')
        self.assertFalse(report['target']['hardware_acknowledgment_verified'])
        self.assertFalse(report['installable'])

    def test_pixel_shift_retains_first_frame_sequence_in_64_paired_cases(self):
        from cp_sequence_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 64)
        self.assertFalse(report['physical_shift_verified'])
        for case in report['cases']:
            args, result = case['input'], case['target']
            if args['mode'] == 23:
                self.assertEqual(result['sequence_index'], 4 if args['first_flag'] else 9)
            self.assertFalse(result['configuration_executed'])
            self.assertFalse(result['callback_executed'])

    def test_dispatched_mode_reaches_capture_snapshot_via_native_memcpy(self):
        from cp_config_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 8)
        for case in report['cases']:
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertTrue(result['native_copy_executed'])
            self.assertEqual(result['copied_bytes'], 0xd64)
            self.assertTrue(result['configuration_snapshot_equal'])
            self.assertEqual(result['capture_configuration_trinity'], result['mode_dispatch']['mode'])
            self.assertFalse(result['scheduler_between_entries_executed'])
            self.assertFalse(result['capture_executed'])

    def test_native_frame_mapping_carries_trinity_to_later_control_flag(self):
        from cp_frame_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 24)
        self.assertFalse(report['installable'])
        for case in report['cases']:
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual(result['control_flag'], result['frame_mode'])
            self.assertTrue(result['mode_never_reassigned_by_host'])
            self.assertFalse(result['full_preparation_executed'])
            self.assertFalse(result['transport_executed'])
            self.assertFalse(result['physical_shift_verified'])

    def test_trinity_index_reaches_serial_extension_without_host_reassignment(self):
        from cp_serial_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 56)
        for case in report['cases']:
            args, result = case['input'], case['target']
            self.assertEqual(result, case['reference'])
            index = args['ordinal'] & 127
            packed = index | (args['trinity'] << 7)
            extended = int(args['interface_mode'] in (4, 5))
            raw = bytes.fromhex(result['packet'])
            self.assertEqual(result['native_index'], index)
            self.assertEqual(result['packed_index'], packed)
            self.assertEqual(result['extended'], extended)
            self.assertEqual(result['tc_first_frame'], int(args['ordinal'] == 0))
            self.assertEqual(raw[:3], b'\x39\x05\x05')
            self.assertEqual(raw[0x6e], packed if extended else 0xa5)
            self.assertEqual(result['transmitted_bytes'], 128 if args['long_packet'] else 100)
            self.assertEqual(result['total_bytes'], result['transmitted_bytes'])
            self.assertEqual(result['repeat_count'], 1)
            self.assertEqual(result['rx_buffer_offset'], 128)
            primary, extension = 0x0f0f, 0
            for value in struct.unpack('<49H', raw[:98]):
                primary ^= value
            for value in struct.unpack('<13H', raw[100:126]):
                extension ^= value
            self.assertEqual(struct.unpack_from('<H', raw, 98)[0], primary)
            self.assertEqual(struct.unpack_from('<H', raw, 126)[0], extension)
            self.assertTrue(result['native_slices_only'])
            self.assertTrue(result['synthetic_frame_and_interface'])
            self.assertFalse(result['full_tc_calculation_executed'])
            self.assertFalse(result['serial_transport_executed'])
            self.assertFalse(result['serial_peer_identified'])
            self.assertFalse(result['physical_shift_verified'])

    def test_factory_tc_defaults_use_native_lookup_copy_and_branch_selection(self):
        from cp_defaults_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 2)
        for case in report['cases']:
            for result in (case['target'], case['reference']):
                self.assertEqual(result['sio_channel'], 4)
                self.assertEqual(result['sio_rate_code'], 24)
                self.assertEqual(result['interface_parameter'], '0x000f0001')
                self.assertEqual(result['native_copied_bytes'], 256)
                self.assertEqual(result['raw_interface_word'], 0x66)
                self.assertEqual(result['decoded_interface_type'], 6)
                self.assertTrue(result['alternate_tc_if_defaults_retained'])
                self.assertTrue(result['native_memcpy_executed'])
                self.assertEqual(result['mutex_calls_omitted'], 5)
                self.assertFalse(result['runtime_overrides_executed'])
                self.assertFalse(result['live_state_verified'])
                self.assertFalse(result['camera_io'])
                self.assertFalse(result['physical_shift_verified'])

    def test_darwin_native_receive_and_parser_prefix_preserve_all_34_bytes(self):
        from darwin_capture_replay import compare
        c2, cr = self.c2 / 'darwin_core.bin', self.cr / 'darwin_core.bin'
        if not c2.is_file() or not cr.is_file():
            self.skipTest('Needs privately extracted 0640_darwin/darwin_core.bin beside each CP image')
        report = compare(c2, cr)
        self.assertEqual(report['paired_cases'], 276)
        self.assertFalse(report['camera_io'])
        self.assertFalse(report['installable'])
        for case in report['cases']:
            self.assertEqual(case['target'], case['reference'])
            result = case['target']
            self.assertEqual(result['message_id'], 12)
            self.assertEqual(result['code'], '03/01/02')
            self.assertEqual(result['received_bytes'], 34)
            self.assertEqual(result['native_snapshot_bytes'], 34)
            self.assertEqual(result['native_fetch_bytes'], 34)
            self.assertEqual(result['external_calls_omitted'], 0)
            self.assertTrue(result['parser_prefix_only'])
            self.assertFalse(result['serial_transport_executed'])
            self.assertFalse(result['capture_preparation_executed'])
            self.assertFalse(result['physical_shift_verified'])

    def test_factory_selected_alternate_tc_retains_ordinal_across_both_banks(self):
        from cp_alternate_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_sequences'], 8)
        self.assertEqual(report['paired_cases'], 32)
        for case in report['cases']:
            args, result = case['input'], case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual(result['official_interface_type'], 6)
            self.assertTrue(result['official_selector_preserved'])
            self.assertTrue(result['native_alternate_entry_executed'])
            self.assertEqual([shot['bank'] for shot in result['shots']], [1, 0, 1, 0])
            mode = 4 if not args['gate'] else 1 if args['shared_flag'] else 2
            for index, shot in enumerate(result['shots']):
                self.assertEqual(shot['ordinal'], index)
                self.assertEqual(shot['control_mode'], mode)
                self.assertEqual(shot['request_category'], 3 if index == 0 and args['first'] else 7)
            self.assertEqual(result['gpio_port'], 255)
            self.assertEqual(result['gpio_native_invalid_port_returns'],
                             ['set' if mode == 1 else 'clear'] * 4)
            self.assertFalse(result['gpio_hardware_access_executed'])
            self.assertFalse(result['serial_transport_executed'])
            self.assertFalse(result['physical_shift_verified'])

    def test_native_ordinal_vector_uses_factory_scales_and_real_flag_copy(self):
        from cp_vector_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_sequences'], 3)
        self.assertEqual(report['paired_cases'], 12)
        for case in report['cases']:
            self.assertEqual(case['target'], case['reference'])
            result = case['target']
            self.assertEqual(result['original_scale_bytes'], [0, 0, 0])
            self.assertTrue(result['interface_selector_preserved'])
            factor = 1 << (case['exponent'] or 13)
            scales = case['scales'] or [0, 0, 0]
            for index, shot in enumerate(result['shots']):
                x, y = [(0, 0), (2, 0), (2, 2), (0, 2)][index]
                self.assertEqual(shot['vector_raw'],
                                 [x * scales[0] * factor, x * scales[1] * factor, y * scales[2] * factor])
                self.assertEqual(shot['native_pattern_mode'], 2)
                self.assertTrue(shot['native_frame_flag_exported'])
                self.assertEqual(shot['native_shared_copy_bytes'], 192)
                self.assertTrue(shot['ordinal_unchanged'])
                self.assertEqual(shot['sensitivity_scales_synthetic'], case['scales'] is not None)
                self.assertFalse(shot['physical_units_verified'])
                self.assertFalse(shot['serial_transport_executed'])
                self.assertFalse(shot['physical_shift_verified'])

    def test_alternate_wire_retains_vector_and_rejects_bad_synthetic_replies(self):
        from cp_alternate_wire_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_packets'], 8)
        self.assertEqual(report['paired_reply_cases'], 24)
        self.assertFalse(report['hardware_acknowledgment_verified'])
        self.assertFalse(report['installable'])
        for case in report['cases']:
            self.assertEqual(case['target'], case['reference'])
            self.assertEqual(case['target']['original_scale_bytes'], [0, 0, 0])
            for shot in case['target']['shots']:
                packet = bytes.fromhex(shot['packet'])
                self.assertEqual(len(packet), 40)
                self.assertEqual(packet[:4], bytes([0x39, 8, 8, 2]))
                self.assertEqual(list(struct.unpack_from('<3i', packet, 4)), shot['packet_vector_raw'])
                self.assertEqual(packet[28], 1)
                checksum = 0x0f0f
                for word in struct.unpack('<19H', packet[:38]):
                    checksum ^= word
                self.assertEqual(struct.unpack_from('<H', packet, 38)[0], checksum)
                self.assertEqual([r['native_validation_branch'] for r in shot['reply_cases']],
                                 ['accepted', 'rejected', 'rejected'])
                self.assertEqual([r['complete_40_byte_copy'] for r in shot['reply_cases']],
                                 [True, False, False])
                self.assertTrue(shot['synthetic_reply_bytes'])
                self.assertFalse(shot['transport_executed'])
                self.assertFalse(shot['hardware_acknowledgment_verified'])
                self.assertFalse(shot['exposure_or_centering_executed'])

    def test_capture_status_exchange_retains_native_request_failure_gate(self):
        from capture_gate_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 102)
        self.assertFalse(report['physical_readiness_verified'])
        for case in report['cases']:
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual(result['event'], 0x1000212 if result['software_gate_passed'] else 0x1000213)
            self.assertEqual(result['ap_status'], int(not result['software_gate_passed']))
            self.assertTrue(result['status_provider_synthetic'])
            self.assertFalse(result['cp_refresh_executed'])
            self.assertFalse(result['transport_executed'])
            self.assertFalse(result['event_dispatcher_executed'])

    def test_trigger_arbitration_distinguishes_af_awbl_and_capture_start(self):
        from cp_trigger_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 72)
        for case in report['cases']:
            result = case['target']
            self.assertEqual(result, case['reference'])
            self.assertFalse(result['physical_shift_verified'])
            self.assertFalse(result['transport_executed'])
            if case['stage'] == 'arbitration':
                args = case['input']
                self.assertFalse(result['sender_bodies_executed'])
                if args == dict(active=[20], previous=(0, 0, 0), af_enabled=1):
                    self.assertEqual(result['selected'], [20, 20, 20])
                    self.assertEqual([r['command'] for r in result['requests']],
                                     ['0x3021', '0x300e', '0x302e'])
                if args['active'] == [20] and args['previous'] == (20, 20, 20):
                    self.assertEqual(result['requests'], [])
                continue
            messages = [bytes.fromhex(m) for m in result['messages']]
            commands = [struct.unpack_from('<I', m, 4)[0] for m in messages]
            command = case['input']['command']
            expected = {0x300c: [0x8202, 0x100], 0x300e: [0x102],
                        0x300f: [0x8204, 0x104], 0x3010: [0x8201, 0x103],
                        0x3021: [0x8301], 0x3022: [0x8302],
                        0x302e: [0x8307], 0x302f: [0x8308]}
            self.assertEqual(commands, expected[command])
            for message in messages:
                self.assertEqual(struct.unpack_from('<II', message, 8),
                                 (case['input']['capture_id'], 0x90040193))
            if 'route' in result:
                route = result['route']
                self.assertFalse(route['capture_handler_executed'])
                self.assertFalse(route['capture_executed'])
                self.assertFalse(route['queue_and_scheduler_executed'])
                if command == 0x300c:
                    self.assertEqual(route['boundary'], 'capture-start-handler')
                    self.assertEqual(route['trigger'], 20)
                    self.assertEqual(struct.unpack_from('<I', messages[1], 20)[0], 0x87654321)
                elif command == 0x300e:
                    self.assertEqual(route['boundary'], 'af-prepare-helper')
                    self.assertEqual(route['awbl_flag'], 0xa5)
                else:
                    self.assertEqual(route['boundary'], 'post-handler')
                    self.assertEqual(route['awbl_flag'], int(command == 0x302e))

    def test_individual_option_support_is_separate_from_parent_support(self):
        from option_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 78)
        change = report['emulated_c2_four_shot_options']
        self.assertEqual([r['visible_by_model'] for r in change['before']], [False, False, False])
        self.assertEqual([r['visible_by_model'] for r in change['after']], [True, True, False])
        self.assertFalse(change['strict_value_two']['visible_by_model'])
        self.assertEqual([r['slot'] for r in change['before']], [9, 9, 9])
        self.assertEqual([r['value'] for r in change['before']], [0, 1, 2])
        self.assertFalse(report['installable'])
        self.assertFalse(report['physical_shift_verified'])

    def test_invalid_native_selection_stops_at_unhandled_path(self):
        from native_replay import select_sequence
        for mode, interval in [(1, 9), (2, 99), (0, 0)]:
            with self.assertRaises(ValueError):
                select_sequence(self.c2, mode, interval)

    def test_parameter_definition_is_separate_from_menu_support_and_value_validation(self):
        from eligibility_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['original_instruction_cases'], 26)
        self.assertFalse(report['target']['defined'])
        self.assertEqual(report['reference']['allowed_values'], [1, 1, 1])
        self.assertEqual(report['native_classification'], dict(c2=False, reference=True, emulated_c2=True))
        for case in report['value_cases']:
            self.assertTrue(case['c2'])  # The permissive fallback does not mean the feature exists.
            self.assertEqual(case['reference'], case['value'] in (0, 1, 2))
            self.assertEqual(case['emulated_c2'], case['reference'])
        init = report['initialization_notifications']
        self.assertEqual([r['inhibited_item'] for r in init['original']], ['0x28c', '0x2927', '0x2928', '0x2929'])
        self.assertEqual(init['emulated_definition'], [])
        self.assertFalse(init['notifier_executed'])
        self.assertFalse(report['installable'])

    def test_native_exclusion_rules_allow_pasm_but_inhibit_auto(self):
        from eligibility_replay import c2_rules
        rules = c2_rules(self.c2)
        self.assertEqual(len(rules), 10)
        exposure = next(r for r in rules if r['name'] == 'PRM_exposure_mode')
        by_name = {r['name']: r['effects'] for r in exposure['values']}
        for mode in ('P', 'A', 'S', 'M'):
            self.assertEqual(by_name['VAL_exposure_mode_EXPOSURE_MODE_STILL_' + mode], [])
        self.assertTrue(any(e['kind'] == 6 and e['operand_a'] == '0x28c'
                            for e in by_name['VAL_exposure_mode_EXPOSURE_MODE_STILL_AUTO']))

    def test_start_sequence_has_its_own_complete_inhibition_set(self):
        from eligibility_replay import c2_rules
        rules = c2_rules(self.c2, start_function=True)
        self.assertEqual(len(rules), 16)
        conditions = {row['condition'] for row in rules}
        # Starting a sequence has independent media, IBIS-error, current-state
        # and preview conditions. Checking only the setting's ten rules misses them.
        self.assertTrue({'0x144', '0x28c', '0x3ac', '0x3ae', '0x5ed',
                         '0x8b5', '0x996', '0x997'}.issubset(conditions))

    def test_program_shift_reset_is_not_sensor_pixel_shift_reset(self):
        from reset_semantics_audit import audit
        for directory in (self.c2, self.cr):
            report = audit(directory)
            self.assertEqual(report['rtti'], 'N5model32sequence_set_program_shift_resetE')
            self.assertEqual(report['command'], '0x4043')
            self.assertEqual(report['label'], 'PID_SET_P_SHIFT_RESET')
            self.assertEqual(report['drive']['command'], '0x401b')
            self.assertEqual(report['drive']['rtti'], 'N5model32sequence_set_program_shift_driveE')
            self.assertTrue(report['cp']['field_is_program_exposure_shift'])
            self.assertEqual(report['cp']['drive_field'], 'sc_PShiftDrive')
            self.assertFalse(report['sensor_pixel_shift_reset'])
            self.assertFalse(report['camera_io'])

    def test_all_unit_shadows_come_through_original_readers_and_preserve_source(self):
        from cp_shadow_load_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 16)
        for case in report['cases']:
            result = case['target']
            key = int(case['input']['key'], 16)
            self.assertTrue(result['original_shadow_read_wrapper_executed'])
            self.assertTrue(result['source_preserved'])
            self.assertFalse(result['host_copied_bytes_into_shadow'])
            self.assertFalse(result['persistent_write_executed'])
            self.assertFalse(result['callback_registration_executed'])
            self.assertFalse(result['parameter_physical_units_identified'])
            if key == 0:
                self.assertEqual(len(result['units']), 19)
                self.assertEqual([int(r['key'], 16) for r in result['units']],
                                 list(range(0x02a40000, 0x02a40013)))
            elif key == 0x02a40013:
                self.assertEqual(result['native_status'], 0xffffffff)
                self.assertEqual(result['units'], [])
                self.assertFalse(result['native_arm_memcpy_executed'])
            else:
                self.assertEqual(len(result['units']), 1)
                self.assertEqual(result['units'][0]['key'], hex(key))
                self.assertEqual(result['units'][0]['bytes'], 256 if key == 0x02a4000b else 1792)
        self.assertFalse(report['physical_shift_verified'])

    def test_unit0b_grid_scales_with_image_geometry_and_indexes_image_bytes(self):
        from cp_grid_source_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 24)
        by_case = {}
        for case in report['cases']:
            result = case['target']
            self.assertEqual(result['coordinate_pairs_copied'], 9)
            self.assertEqual(result['shadow_bytes_written'], 48)
            self.assertTrue(result['runtime_and_shadow_stores_match'])
            self.assertTrue(result['native_generated_coordinate_addresses_image_buffer'])
            self.assertTrue(result['separately_invoked_image_sampler_executed'])
            self.assertEqual(result['sampled_image_bytes'], 4)
            self.assertEqual(result['sampled_value'], '0x8c48a8')
            self.assertFalse(result['persistence_api_executed'])
            self.assertFalse(result['actuator_or_exposure_executed'])
            by_case[(result['mode'], result['image_width_field'], result['image_height_field'])] = result
        self.assertEqual(by_case[(0, 640, 480)]['transformed_pairs'],
                         by_case[(3, 640, 480)]['transformed_pairs'])
        self.assertNotEqual(by_case[(0, 640, 480)]['transformed_pairs'],
                            by_case[(0, 1280, 720)]['transformed_pairs'])
        self.assertFalse(report['physical_shift_verified'])

    def test_native_cache_reduction_records_samples_before_scale_and_vector_calculation(self):
        from cp_scale_acquisition_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 8)
        self.assertEqual(report['paired_vector_steps'], 32)
        normal = []
        for case in report['cases']:
            result = case['target']
            calculation = result['scale_calculation']
            acquisition = calculation['native_acquisition']
            count = case['input']['count']
            self.assertEqual(acquisition['original_reduction_calls'], 4*count)
            self.assertEqual(acquisition['original_collector_calls'], 4*count)
            self.assertEqual(acquisition['measurement_sample_bytes'], 16*count)
            self.assertEqual(acquisition['native_cursor_advanced_bytes'], 16*count)
            self.assertEqual(acquisition['native_written_sample_halfwords'], 8*count)
            self.assertFalse(acquisition['host_assigned_sample_halfwords'])
            self.assertFalse(acquisition['raw_feedback_transport_executed'])
            self.assertFalse(acquisition['full_adjustment_script_executed'])
            self.assertFalse(calculation['host_assigned_scale_bytes'])
            self.assertFalse(calculation['notification_executed'])
            self.assertTrue(calculation['native_local_control_record_update_executed'])
            self.assertTrue(calculation['native_function_return_executed'])
            self.assertTrue(calculation['native_callee_saved_registers_preserved'])
            self.assertTrue(calculation['native_script_index_advanced'])
            self.assertFalse(calculation['physical_notification_delivered'])
            self.assertTrue(result['same_ram'])
            self.assertTrue(result['native_full_consumer_producer_and_packet_formatters'])
            self.assertEqual(len(result['shots']), 4)
            if case['input']['x'] == 200 and case['input']['y'] == 100:
                self.assertEqual(calculation['native_error_flag'], 0)
                normal.append(calculation['scale_bytes'])
            else:
                self.assertEqual(calculation['native_error_flag'], 1)
                self.assertEqual(calculation['scale_bytes'][0 if case['input']['x'] == 0 else 1], 0)
        self.assertEqual(normal, [[4, 8, 8]]*6)
        self.assertFalse(report['physical_shift_verified'])

    def test_native_register_selection_copies_complete_input_without_ready_claims(self):
        from cp_input_source_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 64)
        statuses, selections = set(), {}
        for case in report['cases']:
            inputs, result = case['input'], case['target']
            self.assertEqual(result['native_register_reads'], 2*sum(inputs['present']))
            self.assertEqual(result['register_masks_bits'], [13, 14])
            self.assertEqual(result['native_fixed_point_fraction_bits'], 12)
            self.assertEqual(result['native_snapshot_copied_bytes'], 340)
            self.assertEqual(result['native_availability_return'], inputs['available'])
            statuses.add(result['native_availability_return'])
            self.assertTrue(result['original_source_words_preserved'])
            self.assertTrue(result['peripheral_register_values_and_mappings_are_synthetic'])
            for field in ('host_assigned_selected_or_snapshot_bytes', 'host_assigned_api_returns',
                          'backend_initialization_executed', 'full_cache_update_caller_executed',
                          'automatically_scheduled', 'physical_feedback_identity_verified',
                          'physical_ready_or_settled_ack_verified', 'camera_io', 'installable'):
                self.assertFalse(result[field], field)
            selections[(inputs['flags'], inputs['present'], inputs['same_rows'], inputs['policy'])] = result
        self.assertEqual(statuses, {0, 1})
        self.assertEqual(selections[((1, 0), (1, 1), False, 1)]['decoded_words'], [291, 1110])
        self.assertEqual(selections[((0, 1), (1, 1), False, 1)]['decoded_words'], [387, 273])
        self.assertEqual(selections[((1, 1), (1, 1), False, 1)]['selected_source'], 1)
        self.assertEqual(selections[((1, 1), (1, 1), True, 1)]['selected_source'], 0)
        self.assertEqual(selections[((1, 1), (1, 1), True, 0)]['selected_source'], 1)
        self.assertEqual(selections[((0, 0), (0, 0), True, 0)]['decoded_words'], [0, 0])
        self.assertFalse(report['physical_shift_verified'])

    def test_native_handle_copy_and_binding_feed_original_input_reader(self):
        from cp_context_source_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 16)
        for case in report['cases']:
            result = case['target']
            context = result['context_initialization']
            self.assertEqual(context['native_selected_register_handle_words_copied'], 2)
            self.assertEqual(context['native_handle_entries_checked'], 100)
            self.assertEqual(context['native_assignment_bytes_checked'], 924)
            self.assertEqual(context['native_context_bytes_checked'], 200)
            self.assertEqual(context['native_interface_types'], {
                'reader': 'N6Camera7CamCore13DevEdgeGetterE',
                'configuration': 'N6Camera7CamCore13DevEdgeSetterE'})
            self.assertTrue(context['original_constructor_types_audited'])
            self.assertFalse(context['original_constructors_executed'])
            for field in ('native_child_pointer_bound', 'original_context_binder_returned',
                          'native_callee_saved_registers_preserved', 'source_handle_bank_preserved',
                          'destination_first_words_preserved',
                          'source_handles_and_auxiliary_pointers_are_fixtures'):
                self.assertTrue(context[field], field)
            for field in ('host_assigned_consumed_child_or_register_bases',
                          'backend_initialization_executed', 'full_pipeline_dispatch_executed',
                          'register_bases_are_verified_camera_addresses',
                          'sensor_position_or_settling_verified'):
                self.assertFalse(context[field], field)
            self.assertEqual(result['native_register_reads'], 2*sum(case['input']['present']))
            self.assertEqual(result['native_snapshot_copied_bytes'], 340)
            self.assertEqual(result['native_availability_return'], 0)
            self.assertFalse(result['host_assigned_selected_or_snapshot_bytes'])
            if case['input']['present'] == (1, 1):
                expected = {(0, 0): [0, 0], (1, 0): [291, 1110],
                            (0, 1): [387, 273], (1, 1): [387, 273]}
                self.assertEqual(result['decoded_words'], expected[case['input']['flags']])
        self.assertFalse(report['physical_shift_verified'])
        self.assertFalse(report['installable'])

    def test_native_device_descriptor_binding_preserves_absence_before_input_copy(self):
        from cp_device_binding_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 64)
        for case in report['cases']:
            inputs, result = case['input'], case['target']
            enabled = tuple(a and b for a, b in zip(inputs['present'], inputs['descriptors_present']))
            context = result['context_initialization']
            binding = context['source_initialization']
            self.assertEqual(binding['native_device_binder_calls'], 2)
            self.assertEqual(binding['native_written_words'], 15*sum(enabled))
            self.assertEqual(binding['native_full_getter_bank_checked_bytes'], 924)
            for field in ('native_function_returns_and_callee_saved_registers_verified',
                          'source_descriptors_preserved', 'missing_source_handles_left_unchanged',
                          'device_descriptors_are_fixtures'):
                self.assertTrue(binding[field], field)
            for field in ('output_base_words_host_assigned', 'hardcoded_setter_mapper_used_as_getter',
                          'physical_mmio_access_executed', 'normal_shooting_entry_verified'):
                self.assertFalse(binding[field], field)
            self.assertFalse(context['source_handles_host_assigned'])
            self.assertFalse(context['host_assigned_consumed_child_or_register_bases'])
            self.assertTrue(context['auxiliary_pointers_are_fixtures'])
            self.assertEqual(result['native_register_reads'], 2*sum(enabled))
            self.assertEqual(result['native_snapshot_copied_bytes'], 340)
            self.assertEqual(result['native_availability_return'], 0)
        self.assertFalse(report['camera_io'])
        self.assertFalse(report['physical_shift_verified'])
        self.assertFalse(report['installable'])

    def test_original_device_pool_constructs_then_stops_before_register_writes(self):
        from cp_device_acquire_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 36)
        for case in report['cases']:
            inputs, result = case['input'], case['target']
            self.assertTrue(result['original_pool_initializer_returned'])
            self.assertEqual(result['original_backend_constructor_returned'], inputs['construct_backend'])
            if inputs['channel'] < 2:
                self.assertEqual(result['native_free_objects'], 7)
                self.assertTrue(result['original_constructor_returned'])
                self.assertTrue(result['real_vtable_dispatch_executed'])
                self.assertTrue(result['native_atomic_instructions_executed'])
                self.assertEqual(result['native_zeroed_scratch_bytes'], 2790)
                self.assertIsNone(result['native_status'])
                if inputs['construct_backend']:
                    self.assertEqual(result['boundary'], 'before_register_writing_initializer')
                    self.assertEqual(result['register_initializer_inputs'],
                                     {'register_base': 0, 'control_base': 0, 'mode': 0})
                    self.assertEqual(result['register_initializer_variant'],
                                     'secondary' if inputs['kind'] == 11 else 'primary')
                    self.assertEqual(len(result['native_lock_calls']), 4)
                else:
                    self.assertEqual(result['boundary'], 'before_common_resource_initializer')
                    self.assertIsNone(result['register_initializer_inputs'])
                    self.assertEqual(len(result['native_lock_calls']), 2)
            else:
                self.assertEqual(result['native_status'], 0x10004)
                self.assertEqual(result['native_free_objects'], 8)
                self.assertEqual(result['native_lock_calls'], [])
                self.assertFalse(result['original_constructor_returned'])
            for field in ('output_object_host_assigned', 'common_resource_initializer_returned',
                          'acquisition_completed', 'original_backend_address_binder_returned',
                          'register_writing_initializer_executed', 'actual_device_or_mmio_executed',
                          'physical_shift_verified', 'camera_io', 'installable'):
                self.assertFalse(result[field], field)
        self.assertFalse(report['physical_shift_verified'])

    def test_original_imager_constructs_its_own_model_config_and_dispatches_query(self):
        from cp_startup_config_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 4)
        for case in report['cases']:
            self.assertEqual(case['model_configuration_difference_offsets'],
                             [6, 8, 9, 72, 73, 74, 75, 76, 88, 89, 90, 91, 92, 94, 108])
            for key in ('target', 'reference'):
                result = case[key]
                self.assertTrue(result['original_constructor_returned'])
                self.assertTrue(result['native_singleton_binding'])
                self.assertTrue(result['real_vtable_query_executed'])
                self.assertTrue(result['native_callee_saved_registers_preserved'])
                self.assertEqual(result['native_config_copy_bytes'], 116)
                self.assertEqual(result['native_status'], 0)
                self.assertEqual(len(bytes.fromhex(result['native_config_hex'])), 116)
                self.assertEqual(bytes.fromhex(result['constructor_config_hex'])[6], 8 if key == 'target' else 5)
                self.assertFalse(result['host_assigned_config_or_api_returns'])
                self.assertFalse(result['full_startup_executed'])
                self.assertFalse(result['physical_mmio_access_executed'])
        self.assertFalse(report['physical_shift_verified'])

    def test_native_startup_config_feeds_address_binding_until_real_dma_dependency(self):
        from cp_startup_binding_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 4)
        for case in report['cases']:
            a = case['target']['config_continuation']
            self.assertEqual(a, case['reference']['config_continuation'])
            self.assertTrue(a['original_backend_constructor_returned'])
            self.assertTrue(a['original_address_binding_prefix_executed'])
            self.assertTrue(a['config_preserved'])
            self.assertTrue(a['same_ram'])
            self.assertEqual(a['boundary'], 'before_dma_object_constructor')
            self.assertEqual(a['native_register_writes'], 57)
            self.assertEqual(a['independent_register_words_checked'], 6)
            self.assertEqual(a['config_read_offsets'], [(2, 1), (3, 1), (4, 1), (5, 1), (24, 4), (28, 2)])
            self.assertEqual(a['native_irq_enable_results'], [(0xa2, -17)])
            self.assertTrue(a['irq_id_bounds_are_zero_fixtures'])
            self.assertTrue(a['register_backing_is_synthetic_plain_ram'])
            for field in ('original_address_binder_returned', 'native_irq_enable_succeeded',
                          'hardware_acknowledgement_or_settling_supplied',
                          'physical_mmio_access_executed', 'complete_boot_executed'):
                self.assertFalse(a[field], field)
        self.assertFalse(report['physical_shift_verified'])
        self.assertFalse(report['installable'])

    def test_native_dma_construction_returns_and_preserves_pending_hardware_poll(self):
        from cp_startup_binding_replay import compare
        report = compare(self.c2, self.cr, continue_dma=True)
        self.assertEqual(report['paired_cases'], 4)
        for case in report['cases']:
            result = case['target']['config_continuation']
            self.assertEqual(result, case['reference']['config_continuation'])
            self.assertTrue(result['original_dma_constructor_returned'])
            self.assertEqual(result['boundary'], 'before_repeating_hardware_poll')
            self.assertEqual(result['native_register_writes'], 186)
            self.assertEqual(result['independent_dma_register_words_checked'], 20)
            self.assertEqual(result['independent_dma_route_words_checked'], 5)
            self.assertTrue(result['dma_route_table_from_original_image'])
            self.assertEqual(result['hardware_poll'], {'address': '0xf3830810',
                'value': case['input']['initial_register_word'] | 1, 'wait_mask': 0x10001})
            self.assertEqual([row['mode'] for row in result['native_dma_records']],
                             [0x440, 0x440, 0x440, 0x660, 0x19e])
            self.assertEqual([len(row['descriptor_ids']) for row in result['native_dma_records']],
                             [4, 4, 4, 6, 3])
            self.assertEqual(result['native_irq_enable_results'], [(0xa2, -17)])
            self.assertTrue(result['same_ram'])
            self.assertTrue(result['register_backing_is_synthetic_plain_ram'])
            for field in ('original_address_binder_returned', 'native_irq_enable_succeeded',
                          'dma_data_transfer_or_capture_emulated', 'hardware_acknowledgement_or_settling_supplied',
                          'physical_mmio_access_executed', 'complete_boot_executed'):
                self.assertFalse(result[field], field)
        self.assertFalse(report['camera_io'])
        self.assertFalse(report['physical_shift_verified'])
        self.assertFalse(report['installable'])

    def test_original_caller_supplies_capture_gate_to_snapshot_and_trinity_policy(self):
        from cp_capture_gate_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 96)
        groups = {}
        for case in report['cases']:
            inputs, result = case['input'], case['target']
            self.assertEqual(result, case['reference'])
            self.assertEqual(result['native_gate'], result['native_snapshot_flag_d88'])
            self.assertEqual(result['propagated_trinity'], inputs['trinity'])
            self.assertEqual(result['native_snapshot_copy_bytes'], 0xd64)
            for field in ('native_snapshot_returned_to_caller', 'live_getter_pointer_matches_snapshot', 'same_ram'):
                self.assertTrue(result[field], field)
            for field in ('host_assigned_capture_flag_or_api_returns', 'full_outer_caller_executed',
                          'automatically_scheduled', 'data_block_9416_used_as_live_source',
                          'positioning_or_exposure_executed', 'camera_io', 'installable'):
                self.assertFalse(result[field], field)
            if result['selected_mode'] == 0x17:
                self.assertEqual(result['final_trinity'], inputs['trinity'])
            else:
                self.assertEqual(result['final_trinity'], 0)
            self.assertEqual(result['diagnostic_calls_omitted'], int(inputs['trinity'] != result['final_trinity']))
            if inputs['capture_mode'] == 6:
                self.assertEqual(result['native_gate'], 0)
            if inputs['capture_mode'] == 2:
                enabled = int(bool(inputs['override'] or inputs['pipeline']))
                self.assertEqual(result['native_gate'], enabled)
                self.assertEqual(result['selected_mode'], 0x17 if enabled and not inputs['native_state'] else 2)
            key = tuple(inputs[name] for name in ('capture_mode', 'override', 'pipeline', 'native_state'))
            groups.setdefault(key, []).append((result['native_gate'], result['selected_mode']))
        # The flag/mode gate is shared capture behavior, not a TRINITY-only switch.
        self.assertEqual(len(groups), 48)
        self.assertTrue(all(len(values) == 2 and values[0] == values[1] for values in groups.values()))
        self.assertFalse(report['physical_shift_verified'])

    def test_native_context_and_capturing_level_writers_feed_capture_policy(self):
        from cp_capture_context_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 192)
        for case in report['cases']:
            inputs, result = case['input'], case['target']
            self.assertEqual(result, case['reference'])
            publication = result['native_context_publication']
            transitions = [int(action == 'enter') for action in inputs['guard_actions']]
            self.assertEqual(publication['native_guard_transitions'], transitions)
            self.assertEqual(publication['native_guard'], transitions[-1])
            self.assertEqual(publication['native_pipeline_pointer_stores'], 1)
            for field in ('native_context_binder_executed', 'native_pipeline_getter_executed',
                          'binder_and_getter_share_object', 'native_helpers_returned',
                          'pipeline_parameters_are_fixtures', 'lifecycle_order_is_fixture'):
                self.assertTrue(publication[field], field)
            for field in ('host_assigned_consumed_pointer_or_guard', 'startup_and_scheduler_executed', 'camera_io'):
                self.assertFalse(publication[field], field)
            if inputs['capture_mode'] == 2:
                eligible = bool(inputs['override'] or inputs['pipeline'])
                expected = 0x17 if eligible and not transitions[-1] else 2
                self.assertEqual(result['selected_mode'], expected)
                self.assertEqual(result['final_trinity'], inputs['trinity'] if expected == 0x17 else 0)
            for field in ('host_assigned_capture_flag_or_api_returns', 'full_outer_caller_executed',
                          'automatically_scheduled', 'positioning_or_exposure_executed', 'installable', 'camera_io'):
                self.assertFalse(result[field], field)
        self.assertFalse(report['physical_shift_verified'])

    def test_native_state_producer_and_gpio_read_publish_capture_pipeline_conditions(self):
        from cp_pipeline_source_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 492)
        retained_cases, policy_retained_cases, secondary_flag_modes = 0, 0, 0
        for case in report['cases']:
            inputs, result = case['input'], case['target']
            self.assertEqual(result, case['reference'])
            publication = result['native_context_publication']
            source = publication['pipeline_source']
            fixture = inputs['pipeline_source']
            self.assertTrue(publication['pipeline_condition_generated_natively'])
            for field in ('source_producer_returned', 'source_and_target_binding_verified',
                          'gpio_inputs_and_mapping_are_fixtures', 'notification_history_is_fixture',
                          'stages_and_register_bindings_are_harness_supplied'):
                self.assertTrue(source[field], field)
            for field in ('host_assigned_computed_flag_or_api_return', 'hardware_acknowledgement_supplied',
                          'complete_configuration_function_executed', 'camera_io'):
                self.assertFalse(source[field], field)
            self.assertEqual(source['producer_branch'], 3)
            self.assertEqual(source['native_gpio_read_offsets'], [0, 0x40 if fixture.get('gpio_output') else 0x10])
            gpio = fixture.get('gpio_bit', 1) ^ int(fixture.get('polarity', 1) == 0)
            expected = int(bool(gpio and fixture.get('enabled', 1)))
            inhibit = int(bool(inputs['native_state'] and fixture.get('inhibit_input')))
            retain = bool(fixture.get('special') or (inhibit and expected))
            if retain:
                expected = fixture.get('retained', 0)
                retained_cases += 1
            self.assertEqual(source['native_inhibit_argument'], inhibit)
            self.assertEqual(source['native_source_flag'], expected)
            self.assertEqual(source['native_pipeline_flag'], expected)
            self.assertEqual(source['source_flag_written'], not retain)
            policy = fixture.get('policy_input', 1)
            policy = 1 if policy == 1 else 2 if policy == 0 else 0
            if not fixture.get('policy_enable', 1) and not fixture.get('special'):
                policy = fixture.get('policy_prior', 0)
                policy_retained_cases += 1
            self.assertEqual(source['native_policy_field'], policy)
            self.assertEqual(result['native_snapshot_flag_d8e'], int(policy == 1))
            selected = inputs['capture_mode']
            if not inputs['native_state']:
                if selected == 2 and (expected or inputs['override']):
                    selected = 0x17
                elif selected == 33 and (expected or inputs['override'] or policy == 1):
                    selected = 1
                    if not expected and not inputs['override'] and policy == 1:
                        secondary_flag_modes += 1
            self.assertEqual(result['selected_mode'], selected)
            self.assertEqual(result['final_trinity'], inputs['trinity'] if selected == 0x17 else 0)
            self.assertFalse(result['positioning_or_exposure_executed'])
            self.assertFalse(result['automatically_scheduled'])
        self.assertGreater(retained_cases, 0)
        self.assertEqual(policy_retained_cases, 12)
        self.assertGreater(secondary_flag_modes, 0)
        self.assertFalse(report['physical_shift_verified'])
        self.assertFalse(report['installable'])

    def test_native_capture_manager_and_queued_request_reach_original_capture_entry(self):
        from cp_capture_request_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 96)
        for case in report['cases']:
            inputs, result = case['input'], case['target']
            self.assertEqual(result, case['reference'])
            manager = result['native_manager_initialization']
            self.assertEqual(manager['native_manager_initializer_calls'], 1)
            self.assertEqual(manager['native_snapshot_calls'], 1)
            self.assertEqual(manager['native_gate'], result['native_snapshot_flag_d88'])
            self.assertTrue(manager['wrapper_returned'])
            self.assertTrue(manager['stack_and_registers_preserved'])
            self.assertFalse(manager['host_assigned_manager_outputs'])
            self.assertFalse(manager['every_wrapper_dependency_executed'])
            self.assertEqual(manager['telemetry_calls_omitted'], 3)
            request = result['native_capture_request']
            for field in ('callback_capture_id_matches', 'original_actor_initializer_executed',
                          'complete_native_sender_executed', 'worker_paused_inside_capture_callback',
                          'actor_handoff_is_fixture', 'queue_os_and_debug_state_are_fixtures'):
                self.assertTrue(request[field], field)
            for field in ('host_assigned_callback_or_api_return', 'host_copied_payload_to_receiver',
                          'worker_returned', 'capture_callback_returned', 'physical_exposure_executed',
                          'telemetry_transport_executed'):
                self.assertFalse(request[field], field)
            self.assertEqual(request['native_sender_return'], 1)
            self.assertEqual(request['native_client_return'], 0)
            self.assertEqual(request['native_queue_send_status'], 0)
            self.assertEqual(request['native_receive_bytes'], 28)
            self.assertEqual(request['original_callback_entries'], 1)
            self.assertEqual(request['native_queue_free_bytes'], 128)
            self.assertEqual(request['native_queue_messages'], 0)
            self.assertEqual(request['native_queue_read_index'], (inputs['queue_start']+32)%128)
            self.assertEqual(request['native_queue_write_index'], request['native_queue_read_index'])
            self.assertEqual(request['telemetry_calls_omitted'], 1)
            selected = inputs['capture_mode']
            if not inputs['native_state']:
                if selected == 2 and (inputs['pipeline'] or inputs['override']):
                    selected = 23
                elif selected == 33:
                    selected = 1  # Native policy field is1 in this selected fixture.
            self.assertEqual(result['selected_mode'], selected)
            self.assertFalse(result['full_outer_caller_executed'])
            self.assertFalse(result['automatically_scheduled'])
            self.assertFalse(result['positioning_or_exposure_executed'])
        self.assertFalse(report['physical_shift_verified'])
        self.assertFalse(report['installable'])

    def test_native_sequence_pool_constructor_and_caller_bind_stage_zero_descriptor(self):
        from cp_sequence_object_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 68)
        failures, starts = 0, 0
        for case in report['cases']:
            inputs, result = case['input'], case['target']
            self.assertEqual(result, case['reference'])
            self.assertTrue(result['original_pool_allocator_executed'])
            self.assertTrue(result['original_descriptor_initializer_executed'])
            self.assertTrue(result['constructor_stack_and_registers_preserved'])
            self.assertTrue(result['image_parameter_and_pool_os_inputs_are_fixtures'])
            for field in ('host_assigned_allocation_result_or_descriptor', 'host_assigned_initial_stage',
                          'outer_capture_prefix_executed', 'actual_image_parameter_allocation_executed',
                          'positioning_or_exposure_executed', 'first_stage_child_executed',
                          'logging_transport_executed', 'camera_io', 'installable'):
                self.assertFalse(result[field], field)
            if inputs.get('failure'):
                failures += 1
                self.assertEqual(result['boundary'], 'sequence_allocation_failed')
                self.assertFalse(result['native_allocation_succeeded'])
                self.assertFalse(result['complete_selector_executed'])
                self.assertFalse(result['stage_zero_callback_dispatched'])
                self.assertIsNone(result['sequence_index'])
                self.assertEqual(result['native_free_count'], 0 if inputs['failure'] == 'empty' else 2)
                continue
            self.assertTrue(result['native_allocation_succeeded'])
            self.assertTrue(result['complete_selector_executed'])
            self.assertTrue(result['original_descriptor_stores_executed'])
            self.assertTrue(result['native_log_filter_executed'])
            self.assertEqual(result['native_free_count'], 1)
            self.assertEqual(result['constructor_stage'], 0)
            expected = 4 if inputs['first'] else 9
            if inputs['mode'] != 23 and inputs['ordinal']:
                expected += 1
            self.assertEqual(result['sequence_index'], expected)
            self.assertEqual(result['exif_lookup_status'], [0] if inputs['exif_present'] else [0xfffffffd])
            self.assertEqual(result['exif_sequence_byte_written'], inputs['exif_present'])
            if expected in (4, 9):
                starts += 1
                self.assertTrue(result['stage_zero_callback_dispatched'])
                self.assertEqual(result['boundary'], 'before_first_stage_child')
            else:
                self.assertFalse(result['stage_zero_callback_dispatched'])
                self.assertEqual(result['boundary'], 'descriptor_bound_control_case')
        self.assertEqual(failures, 4)
        self.assertEqual(starts, 40)
        self.assertFalse(report['physical_shift_verified'])
        self.assertFalse(report['installable'])

    def test_native_sampling_counts_and_stages_do_not_imply_valid_calibration(self):
        from cp_sample_stage_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 12)
        for case in report['cases']:
            inputs = case['input']
            result = case['target']['snapshot_continuation']
            count = inputs['requested_count'] or 2
            words = [291, 1110] if inputs['flags'] == (1, 0) else [387, 273]
            self.assertEqual(result['effective_samples'], count)
            self.assertEqual(result['original_prepare_calls'], 8)
            self.assertEqual(result['original_sample_calls'], 8*count)
            self.assertEqual(result['native_stage_history'], list(range(9)))
            self.assertEqual(result['native_average_halfwords'], [4*words[0]]*4+[4*words[1]]*4)
            self.assertEqual(result['native_script_index'], 16)
            self.assertTrue(result['source_snapshot_preserved'])
            self.assertTrue(result['full_original_sampling_function_executed'])
            self.assertTrue(result['native_callee_saved_registers_preserved'])
            self.assertEqual(result['calibration_validation_bypassed_by_fixture'], not inputs['validate_inputs'])
            self.assertEqual(result['native_validation_rejected_inputs'], inputs['validate_inputs'])
            self.assertEqual(result['native_final_error'], 0x505 if inputs['validate_inputs'] else 0)
            self.assertEqual(result['native_error_history'][-1], result['native_final_error'])
            self.assertEqual(result['native_final_bank'], 0)
            for field in ('host_assigned_averages_or_advanced_stages', 'calibration_success_verified',
                          'full_script_scheduler_executed', 'physical_feedback_or_settling_verified'):
                self.assertFalse(result[field], field)
        self.assertFalse(report['physical_shift_verified'])
        self.assertFalse(report['installable'])

    def test_caif_frame_stays_pending_until_a_real_peer_response(self):
        from cp_caif_frame_replay import compare
        report = compare(self.c2, self.cr)
        self.assertEqual(report['paired_cases'], 8)
        for case in report['cases']:
            result = case['target']
            self.assertEqual(result['native_queue_header'], 'f00301002200')
            self.assertEqual(result['ring_pending_count'], 1)
            self.assertFalse(result['bus_driver_executed'])
            self.assertFalse(result['header_response_supplied'])
            self.assertFalse(result['payload_transmitted'])
            self.assertFalse(result['sensor_or_exposure_sync_verified'])
            if case['input']['peer_high']:
                self.assertEqual(result['state_history'][-1], [3, 1])
                self.assertEqual(result['sio_segment_bytes'], 8)
                self.assertEqual(result['sio_descriptor_live_buffers'], 1)
                self.assertEqual(result['boundary'], 'before_bus_driver')
            else:
                self.assertEqual(result['state_history'][-1], [4, 3])
                self.assertFalse(result['sio_header_request_built'])
                self.assertEqual(result['sio_descriptor_live_buffers'], 0)
        self.assertFalse(report['physical_shift_verified'])
        self.assertFalse(report['installable'])


if __name__ == '__main__':
    unittest.main()
