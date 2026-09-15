import unittest
from pathlib import Path
ROOT = Path(__file__).parents[1]
INSTALL = (ROOT/'install-native-termux-repair.sh').read_text()
RUN = (ROOT/'run_naza.sh').read_text()
MAIN = (ROOT/'main.py').read_text()
REQ = (ROOT/'requirements.in').read_text().lower()
PREFLIGHT = (ROOT/'naza_crypto_preflight.py').read_text()

class NativeBundleTests(unittest.TestCase):
    def test_removed_dependencies(self):
        self.assertNotIn('pennylane==', REQ)
        self.assertNotIn('psutil==', REQ)
        self.assertNotIn('import pennylane', MAIN.lower())
        self.assertNotIn('import psutil', MAIN.lower())

    def test_minimal_liboqs(self):
        self.assertIn('-DOQS_BUILD_ONLY_LIB=ON', INSTALL)
        self.assertIn('-DOQS_MINIMAL_BUILD="KEM_ml_kem_1024;KEM_hqc_256"', INSTALL)
        self.assertIn('cmake --build build --parallel 1', INSTALL)
        self.assertIn('ML-KEM-1024', INSTALL)
        self.assertIn('HQC-256', INSTALL)
        self.assertIn('encap_secret', INSTALL)
        self.assertIn('decap_secret', INSTALL)

    def test_llama_android_loader(self):
        self.assertIn('--no-binary llama-cpp-python', INSTALL)
        self.assertIn('CMAKE_BUILD_PARALLEL_LEVEL=1', INSTALL)
        self.assertIn('LLAMA_CPP_LIB_PATH', INSTALL)
        self.assertIn("libllama.so", INSTALL)
        self.assertIn('ctypes.CDLL', INSTALL)
        self.assertIn('LLAMA_CPP_LIB_PATH', RUN)
        self.assertIn('libllama.so', RUN)
        self.assertIn('ctypes.CDLL', PREFLIGHT)
        self.assertIn('from llama_cpp import Llama', PREFLIGHT)

    def test_native_only_runtime(self):
        self.assertNotIn('termux-fingerprint', RUN)
        self.assertNotIn('proot', RUN.lower())
        self.assertIn('termux-keystore', INSTALL)
        self.assertIn('inside_secure_hardware', INSTALL)
        self.assertIn('enforced_by_secure_hardware', INSTALL)

    def test_offline_default(self):
        self.assertIn('NAZA_OFFLINE_MODE="${NAZA_OFFLINE_MODE:-1}"', RUN)
        self.assertIn('unset HTTP_PROXY HTTPS_PROXY ALL_PROXY', RUN)
        self.assertIn('NAZA_OFFLINE_MODE', MAIN)
        self.assertIn('Network model download is disabled', MAIN)

    def test_preflight_real_crypto(self):
        self.assertIn('oqs.oqs_version()', PREFLIGHT)
        self.assertIn('KeyEncapsulation', PREFLIGHT)
        self.assertIn('tri.create_envelope', PREFLIGHT)
        self.assertIn('tampered[-1] ^= 1', PREFLIGHT)

if __name__ == '__main__':
    unittest.main()
