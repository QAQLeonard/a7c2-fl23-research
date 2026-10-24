"""Actual writer completion paths publish host metadata only after verification."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from looktool import lookfile,devicejob,rawidentity
from test_lookfile import MemoryCamera,PreparedJob
from test_rawprofiles import profile


class HookTests(unittest.TestCase):


    def test_compiled_source_DCP_is_frozen_without_refitting_or_changing_table(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);dcp=root/'source.dcp';dcp.write_bytes(profile('NC'))
            descriptor=rawidentity.descriptor(dcp,'NC');raw=bytes(1215)
            source=root/'source.a7look'
            lookfile.write(source,'NC',raw,method='test',attribution='test',raw_profile=descriptor)
            job=PreparedJob(root/'job',factory=MemoryCamera())
            with patch.object(devicejob.native,'fit_reference',side_effect=AssertionError('Refit forbidden')):
                state=job.create(source,'NC',1,None,root/'backup')
            self.assertEqual(state['raw_profile_binding'],descriptor)
            self.assertEqual(job.received,raw)


if __name__=='__main__':unittest.main()
