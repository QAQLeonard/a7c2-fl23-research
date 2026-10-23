"""Native-result rejection and optional real-source compiler-input checks."""
import copy,json,os,struct,unittest
from pathlib import Path
from looktool import firmware,six,worker

class WorkerReportTests(unittest.TestCase):
    def setUp(self):
        self.contract={'schema':'a7c2-table-worker-contract/1','window_writes':2,
            'sizes':dict(zip(worker.NAMES,[12000,14000])),
            'before':dict(zip(worker.NAMES,['11'*32,'22'*32])),
            'after':dict(zip(worker.NAMES,['11'*32,'33'*32]))}
    def report(self,mode):
        c=self.contract
        before=c['after'] if mode==2 else c['before'];after=c['before'] if mode==2 else c['after']
        return worker.REPORT.pack(b'A7IRP001',1,mode,9,0 if mode==0 else 2,*([0]*6),17,21,22,12000,14000)+b''.join(bytes.fromhex(before[n]) for n in worker.NAMES)+(bytes(64) if mode==0 else b''.join(bytes.fromhex(after[n]) for n in worker.NAMES))
    def test_modes_require_matching_hash_direction_without_claiming_host_or_boot(self):
        for mode in (0,1,2):
            result=worker.validate_worker_report(self.report(mode),mode,self.contract)
            self.assertTrue(result['native_verified']);self.assertFalse(result['host_complete_readback_verified']);self.assertFalse(result['physical_test_verified'])
            with self.assertRaises(ValueError):worker.validate_worker_report(self.report(mode),(mode+1)%3,self.contract)
    def test_failed_phase_status_mount_cleanup_uid_and_counts_are_rejected(self):
        original=self.report(1)
        for index in [1,3,4,5,6,7,8,9,10,12,13,14,15]:
            values=list(worker.REPORT.unpack_from(original));values[index]=0 if index in [3,4,12,13] else values[index]+1
            bad=worker.REPORT.pack(*values)+original[112:]
            with self.assertRaises(ValueError,msg=str(index)):worker.validate_worker_report(bad,1,self.contract)
    def test_truncation_hash_tamper_and_invalid_contract_are_rejected(self):
        for raw in [self.report(1)[:-1],self.report(1)+b'x',self.report(1)[:112]+bytes(128)]:
            with self.assertRaises(ValueError):worker.validate_worker_report(raw,1,self.contract)
        bad=copy.deepcopy(self.contract);bad['after']['appFw.so']='11'
        with self.assertRaises(ValueError):worker.validate_worker_report(self.report(1),1,bad)
    def test_unknown_stock_source_is_rejected_before_manifest_processing(self):
        with self.assertRaises(ValueError):worker.prepare_table_worker(b'stock',b'unknown',{}, {},{})

@unittest.skipUnless(os.environ.get('A7C2_RESEARCH_FIXTURES'),'Requires private real-source fixtures')
class WorkerPrivateSourceTests(unittest.TestCase):
    def setUp(self):
        index=Path(os.environ['A7C2_RESEARCH_FIXTURES']);paths=json.loads(index.read_text())
        self.ap=(index.parent/paths['six_ap']).read_bytes();self.cp=(index.parent/paths['v4_cp']).read_bytes()
        self.f,self.r,self.after=six.replace_tables(self.ap,self.cp,{6:bytes([1])*1215})
        self.f['slot_plan']={'model':'ILCE-7CM2','firmware':'2.01','selected_slots':[6]}
    def test_real_table_transition_yields_native_inputs_and_exact_restore(self):
        header,c=worker.prepare_table_worker(self.ap,self.cp,self.f,self.r,{'6':'ST'})
        self.assertIn('static const struct Window windows[]',header)
        self.assertEqual(c['window_writes'],3);self.assertEqual(c['selected_slots'],[6]);self.assertFalse(c['live_bindings_verified'])
        self.assertEqual(c['before']['cpapp-b.bin'],six.CP_SHA)
        self.assertEqual(c['after']['cpapp-b.bin'],firmware.sha(self.after['cpapp-b.bin']))
        self.assertEqual(c['before']['appFw.so'],c['after']['appFw.so'])
        self.assertEqual(firmware.apply(self.after,self.r)['cpapp-b.bin'],self.cp)
    def test_wrong_binding_slot_scope_and_inverse_are_rejected(self):
        with self.assertRaises(ValueError):worker.prepare_table_worker(self.ap,self.cp,self.f,self.r,{'6':'FL'})
        wrong=copy.deepcopy(self.f);wrong['slot_plan']['selected_slots']=[5]
        with self.assertRaises(ValueError):worker.prepare_table_worker(self.ap,self.cp,wrong,self.r,{'5':'ST'})
        reverse=copy.deepcopy(self.r);reverse['files']['cpapp-b.bin']['after_sha256']='00'*32
        with self.assertRaises(ValueError):worker.prepare_table_worker(self.ap,self.cp,self.f,reverse,{'6':'ST'})

if __name__=='__main__':unittest.main()
