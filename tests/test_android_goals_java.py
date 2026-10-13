"""Execute production Goals.java on the JVM with Android/JSON substitutes."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

class AndroidGoalsJavaTests(unittest.TestCase):
    def test_shared_progress_and_disk_failure(self):
        java=shutil.which('java')
        if not java:
            self.skipTest('JVM unavailable; Android Goals check did not run')
        root=Path(__file__).resolve().parents[1]
        fixtures=Path(__file__).parent/'android_goals_stubs'
        with tempfile.TemporaryDirectory() as folder:
            probe=subprocess.run([java,'com.sun.tools.javac.Main','-version'],capture_output=True,text=True,timeout=10)
            if probe.returncode:
                self.skipTest('Java compiler unavailable; Android Goals check did not run')
            sources=[str(f) for f in fixtures.rglob('*.java')]
            sources.append(str(root/'android/Jarvis3/app/src/main/java/jarvis/Goals.java'))
            sources.append(str(root/'android/Jarvis3/app/src/main/java/jarvis/WakeHolds.java'))
            for name in ('User','KeyVault','Store','GeminiWorkers','Gemini','AndroidSetup'):
                sources.append(str(root/f'android/Jarvis3/app/src/main/java/jarvis/{name}.java'))
            build=subprocess.run([java,'com.sun.tools.javac.Main','-d',folder,*sources],capture_output=True,text=True,timeout=30)
            self.assertEqual(build.returncode,0,build.stdout+build.stderr)
            android=root/'android/Jarvis3/app/src/main/java'
            parse=subprocess.run([java,'-cp',folder,'ParseSources',*[str(p) for p in android.rglob('*.java')]],capture_output=True,text=True,timeout=20)
            self.assertEqual(parse.returncode,0,parse.stdout+parse.stderr)
            self.assertIn('All Android source syntax parsed',parse.stdout)
            run=subprocess.run([java,'-cp',folder,'jarvis.GoalsHarness',folder],capture_output=True,text=True,timeout=30)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertIn('deletion passed',run.stdout)
            wake=subprocess.run([java,'-cp',folder,'jarvis.WakeHoldsHarness'],capture_output=True,text=True,timeout=15)
            self.assertEqual(wake.returncode,0,wake.stdout+wake.stderr)
            self.assertIn('concurrent and duplicate reasons passed',wake.stdout)
            vault=subprocess.run([java,'-cp',folder,'jarvis.KeyVaultHarness'],capture_output=True,text=True,timeout=15)
            self.assertEqual(vault.returncode,0,vault.stdout+vault.stderr)
            self.assertIn('fail closed passed',vault.stdout)
            workers=subprocess.run([java,'-cp',folder,'jarvis.GeminiWorkersHarness'],capture_output=True,text=True,timeout=15)
            self.assertEqual(workers.returncode,0,workers.stdout+workers.stderr)
            self.assertIn('queue bound passed',workers.stdout)
            setup=subprocess.run([java,'-cp',folder,'jarvis.AndroidSetupHarness'],capture_output=True,text=True,timeout=15)
            self.assertEqual(setup.returncode,0,setup.stdout+setup.stderr)
            self.assertIn('credential boundaries passed',setup.stdout)
