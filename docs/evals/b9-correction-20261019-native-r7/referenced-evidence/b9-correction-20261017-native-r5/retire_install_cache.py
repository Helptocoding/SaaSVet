"""Remove only disposable native installer copies after the frozen install succeeds."""
import json
from pathlib import Path
import shutil
from native_support import EVIDENCE, WORK, TREE, save, resources, integrity


def main():
    assert not (EVIDENCE / 'evaluation-seal.json').exists()
    assert not (EVIDENCE / 'install-cache-retirement.json').exists()
    assert json.loads((EVIDENCE / 'frontend-layout.json').read_text())['state'] == 'PASS'
    expected = Path('C:/Users/LAP/AppData/Local/Temp/b9-native-20261017-r5')
    assert WORK.resolve() == expected and not WORK.is_symlink() and not WORK.is_junction()
    roots = [WORK / 'pnpm-store', WORK / 'downloads']
    resolved = []
    for root in roots:
        assert root.is_dir() and not root.is_symlink() and not root.is_junction()
        target = root.resolve()
        assert target.parent == expected and target.name in ('pnpm-store', 'downloads')
        resolved.append(target)
    # No installed package may refer into the store that will be retired.
    links = []
    for path in (TREE / 'frontend/node_modules').rglob('*'):
        if path.is_symlink() or path.is_junction():
            target = path.resolve()
            assert not any(target.is_relative_to(root) for root in resolved), str(path)
            links.append({'path': str(path), 'target': str(target)})
    before = resources()
    inventories = []
    for root in resolved:
        files = [p for p in root.rglob('*') if p.is_file()]
        inventories.append({'resolved_absolute_target': str(root), 'files': len(files),
            'bytes': sum(p.stat().st_size for p in files)})
        assert root.resolve().parent == expected
        shutil.rmtree('\\\\?\\' + str(root))
        assert not root.exists()
        if root.name == 'downloads':
            root.mkdir()  # Later security-tool downloads use the same private directory.
    integrity('after-install-cache-retirement')
    save('install-cache-retirement.json', {'state': 'PASS', 'targets': inventories,
        'installed_package_links_checked': links, 'installed_dependencies_removed': False,
        'candidate_and_lockfiles_changed': False, 'shared_caches_removed': False,
        'source_checksums_retained': 'downloads.json', 'resources_before': before,
        'resources_after': resources(), 'application_tests_executed': False})
    print('PRIVATE_INSTALL_CACHE_RETIRED', flush=True)


if __name__ == '__main__':
    main()
