"""Public guide documents the installed tools and fresh-state contract."""
from pathlib import Path


def test_readme_describes_installed_contract():
    text=(Path(__file__).resolve().parents[1]/'README.md').read_text()
    for name in ('`responsibility`','`trigger`','`respond`','/cadence status','cadence.db'):
        assert name in text
    assert '`pulse`' not in text
