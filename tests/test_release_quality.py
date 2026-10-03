import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tests.test_dialogue_reliability import ROOT, run_js


class ReleaseQualityTests(unittest.TestCase):
    def test_release_identity_rejects_mixed_frontend_and_backend(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = ['release.json', 'shulian_backend/version.py', 'web/app.jsx',
                     'web/data.jsx', 'web/index.html']
            for relative in files:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            script = f"import {{ releaseIdentity }} from {json.dumps((ROOT/'scripts/web-build-shared.mjs').as_uri())};\n"
            script += f"const root={json.dumps(str(root))};\n"
            release = json.loads((ROOT / 'release.json').read_text(encoding='utf-8'))
            run_js(script + 'await releaseIdentity(root);')
            for relative in files[1:]:
                target = root / relative
                original = target.read_text(encoding='utf-8')
                target.write_text(original.replace(release['version'], '0.0.0').replace(
                    release['buildId'], 'wrong-build'), encoding='utf-8')
                run_js(script + "let rejected=false;try{await releaseIdentity(root)}catch(e){rejected=e.message.includes('Release identity mismatch')}if(!rejected)throw Error('mixed release passed');")
                target.write_text(original, encoding='utf-8')

    def test_packaging_requires_quality_gate_and_existing_deployment_copy_matches(self):
        source = (ROOT / 'package-shulian-inplace.ps1').read_bytes()
        # A standalone checkout has no deployment wrapper outside its root.
        # When the local deployment copy exists, it must still match exactly.
        deployment_copy = ROOT.parent / 'package-shulian-inplace.ps1'
        if deployment_copy.exists():
            self.assertEqual(source, deployment_copy.read_bytes())
        script = source.decode('utf-8-sig')
        gate = script.index("& $python (Join-Path $repo 'scripts\\check-quality.py')")
        self.assertLess(gate, script.index('& $npm run build:web'))
        self.assertLess(gate, script.index('& $python -m PyInstaller'))
        self.assertIn('if ($LASTEXITCODE -ne 0)', script[gate:script.index('& $npm run build:web')])
        self.assertNotIn("$repo = 'G:", script)


if __name__ == '__main__':
    unittest.main()
