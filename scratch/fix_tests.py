
import sys

path = 'tests/test_integration.py'
with open(path, 'r') as f:
    content = f.read()

content = content.replace('@pytest.fixture(autouse=True)\\n    def setup(self, monkeypatch):', '@pytest.fixture(autouse=True)\n    def setup(self, monkeypatch):')

with open(path, 'w') as f:
    f.write(content)
