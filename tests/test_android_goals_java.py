"""Execute production Goals.java on the JVM with Android/JSON substitutes."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

class AndroidGoalsJavaTests(unittest.TestCase):
    def _java_calls(self):
        output = ('All Android source syntax parsed; deletion passed; '
                  'concurrent and duplicate reasons passed; fail closed passed; '
                  'queue bound passed; credential boundaries passed')
        completed = subprocess.CompletedProcess([], 0, output, '')
        with patch.object(shutil, 'which', return_value='fixture-java'), patch.object(
                subprocess, 'run', return_value=completed) as run:
            self.test_shared_progress_and_disk_failure()
        self.assertEqual(run.call_count, 8, 'Derleme ve bütün JVM harness adımları çalışmalı.')
        return run.call_args_list

    def test_all_java_steps_capture_utf8_diagnostics_with_replacement(self):
        for call in self._java_calls():
            with self.subTest(command=call.args[0]):
                self.assertTrue(call.kwargs['capture_output'])
                self.assertTrue(call.kwargs['text'])
                self.assertEqual(call.kwargs.get('encoding'), 'utf-8')
                self.assertEqual(call.kwargs.get('errors'), 'replace')

    def test_java_source_and_runtime_encodings_are_explicit(self):
        calls = self._java_calls()
        compile_command = calls[1].args[0]
        self.assertIn('-encoding', compile_command)
        self.assertEqual(compile_command[compile_command.index('-encoding') + 1], 'UTF-8')
        for call in calls[2:]:
            with self.subTest(command=call.args[0]):
                self.assertIn('-Dfile.encoding=UTF-8', call.args[0])

    def test_legacy_encoded_diagnostic_does_not_break_reader(self):
        # Aynı eski Windows hata çıktısını Linux'ta da üretir: 0xFC UTF-8 değildir.
        options = self._java_calls()[1].kwargs
        result = subprocess.run(
            [sys.executable, '-c', "import sys; sys.stderr.buffer.write(b'compiler: \\xfc'); sys.exit(2)"],
            **options)
        self.assertEqual(result.returncode, 2, 'Derleme hatası başarıya çevrilmemeli.')
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, 'compiler: \ufffd')

    def test_shared_progress_and_disk_failure(self):
        java=shutil.which('java')
        if not java:
            self.skipTest('JVM unavailable; Android Goals check did not run')
        root=Path(__file__).resolve().parents[1]
        fixtures=Path(__file__).parent/'android_goals_stubs'
        with tempfile.TemporaryDirectory() as folder:
            probe=subprocess.run([java,'com.sun.tools.javac.Main','-version'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=10)
            if probe.returncode:
                self.skipTest('Java compiler unavailable; Android Goals check did not run')
            sources=[str(f) for f in fixtures.rglob('*.java')]
            sources.append(str(root/'android/Jarvis3/app/src/main/java/jarvis/Goals.java'))
            sources.append(str(root/'android/Jarvis3/app/src/main/java/jarvis/WakeHolds.java'))
            for name in ('User','KeyVault','Store','GeminiWorkers','Gemini','AndroidSetup'):
                sources.append(str(root/f'android/Jarvis3/app/src/main/java/jarvis/{name}.java'))
            build=subprocess.run([java,'com.sun.tools.javac.Main','-encoding','UTF-8','-d',folder,*sources],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
            self.assertEqual(build.returncode,0,build.stdout+build.stderr)
            android=root/'android/Jarvis3/app/src/main/java'
            parse=subprocess.run([java,'-Dfile.encoding=UTF-8','-cp',folder,'ParseSources',*[str(p) for p in android.rglob('*.java')]],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20)
            self.assertEqual(parse.returncode,0,parse.stdout+parse.stderr)
            self.assertIn('All Android source syntax parsed',parse.stdout)
            run=subprocess.run([java,'-Dfile.encoding=UTF-8','-cp',folder,'jarvis.GoalsHarness',folder],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertIn('deletion passed',run.stdout)
            wake=subprocess.run([java,'-Dfile.encoding=UTF-8','-cp',folder,'jarvis.WakeHoldsHarness'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=15)
            self.assertEqual(wake.returncode,0,wake.stdout+wake.stderr)
            self.assertIn('concurrent and duplicate reasons passed',wake.stdout)
            vault=subprocess.run([java,'-Dfile.encoding=UTF-8','-cp',folder,'jarvis.KeyVaultHarness'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=15)
            self.assertEqual(vault.returncode,0,vault.stdout+vault.stderr)
            self.assertIn('fail closed passed',vault.stdout)
            workers=subprocess.run([java,'-Dfile.encoding=UTF-8','-cp',folder,'jarvis.GeminiWorkersHarness'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=15)
            self.assertEqual(workers.returncode,0,workers.stdout+workers.stderr)
            self.assertIn('queue bound passed',workers.stdout)
            setup=subprocess.run([java,'-Dfile.encoding=UTF-8','-cp',folder,'jarvis.AndroidSetupHarness'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=15)
            self.assertEqual(setup.returncode,0,setup.stdout+setup.stderr)
            self.assertIn('credential boundaries passed',setup.stdout)

