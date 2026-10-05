#!/usr/bin/env python3
"""Isolated DSM backing-storage removal fixtures.

Real links model /var/packages -> /volumeN/@appdata|@appconf. Only fixture
paths can be removed. No NAS data, certificate stores or services are accessed.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

spec = importlib.util.spec_from_file_location('storage_lifecycle', Path(__file__).with_name('lifecycle.py'))
lifecycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lifecycle)


class PackageStorage(lifecycle.Lifecycle):
    def setUp(self):
        super().setUp()
        self.record = self.root/'storage.record'
        self.old_key = self.appdata/'root/live/key.pem'
        self.old_key.parent.mkdir(parents=True)
        self.old_key.write_text('fixture-private-key-never-display')
        self.old_key.chmod(0o600)
        self.old_key.parent.parent.chmod(0o700)
        self.settings = self.appconf/'settings.json'
        self.settings.write_text('fixture-cloudflare-token-never-display')
        self.settings.chmod(0o600)

    def capture(self, kind='var', expected=0):
        return self.sh('package_storage_capture "$BASE/'+kind+'" '+kind+' "'+str(self.record)+'"', expected)

    def monitor(self, expected=0, env=None):
        p = subprocess.run(['sh', str(self.removal/'monitor')], env=dict(self.env, **(env or {})),
                           capture_output=True, text=True, timeout=10)
        self.assertEqual(p.returncode, expected, p.stdout+p.stderr)
        return p

    def test_registered_symlink_records_physical_identity_then_removes_backing(self):
        self.capture()
        self.assertTrue(self.old_key.exists(), 'Capture must retain data')
        self.assertEqual(self.record.stat().st_mode & 0o777, 0o600)
        shutil.rmtree(self.base)
        self.sh('package_storage_verify "'+str(self.record)+'" var\npackage_storage_remove "'+str(self.record)+'" var')
        self.assertFalse(self.appdata.exists())
        self.assertTrue(self.settings.exists(), 'VAR cleanup must not delete ETC')

    def test_replacement_directory_is_retained(self):
        self.capture()
        original=self.appdata.with_name('original')
        self.appdata.rename(original)
        self.appdata.mkdir()
        unrelated=self.appdata/'unrelated'; unrelated.write_text('keep')
        self.sh('package_storage_remove "'+str(self.record)+'" var', 1)
        self.assertEqual(unrelated.read_text(), 'keep')
        self.assertTrue((original/'root/live/key.pem').exists())

    def test_replacement_leaf_symlink_is_retained(self):
        self.capture()
        original=self.appdata.with_name('original')
        self.appdata.rename(original)
        self.appdata.symlink_to(original)
        self.sh('package_storage_remove "'+str(self.record)+'" var', 1)
        self.assertTrue(self.appdata.is_symlink())
        self.assertTrue((original/'root/live/key.pem').exists())

    def test_symlink_ancestor_and_outside_storage_are_rejected(self):
        (self.base/'var').unlink()
        outside=self.root/'outside'; outside.mkdir(); (outside/'keep').write_text('keep')
        (self.base/'var').symlink_to(outside)
        self.capture(expected=1)
        (self.base/'var').unlink()
        physical=self.appdata.parent
        original=physical.with_name('storage-original')
        physical.rename(original); physical.symlink_to(original)
        (self.base/'var').symlink_to(self.appdata)
        self.capture(expected=1)
        self.assertEqual((outside/'keep').read_text(), 'keep')

    def test_writable_parent_and_external_child_symlink(self):
        self.appdata.parent.chmod(0o777)
        self.capture(expected=1)
        self.appdata.parent.chmod(0o755)
        outside=self.root/'outside';outside.mkdir();(outside/'keep').write_text('keep')
        (self.appdata/'outside-link').symlink_to(outside)
        self.capture()
        self.sh('package_storage_remove "'+str(self.record)+'" var')
        self.assertEqual((outside/'keep').read_text(),'keep')

    def test_wrong_kind_path_and_non_directory_are_rejected(self):
        self.sh('package_storage_capture "$BASE/etc" var "'+str(self.record)+'"', 1)
        shutil.rmtree(self.appdata)
        self.appdata.write_text('keep-file')
        self.capture(expected=1)
        self.assertEqual(self.appdata.read_text(), 'keep-file')

    def test_nested_mount_is_rejected_before_capture_or_removal(self):
        mountinfo=self.root/'mountinfo'
        mountinfo.write_text('')
        source=self.functions.read_text().replace('/proc/self/mountinfo',str(mountinfo))
        self.functions.write_text(source)
        self.capture()
        mountinfo.write_text('42 1 0:1 / '+str(self.appdata)+'/nested rw - tmpfs tmpfs rw\n')
        self.sh('package_storage_remove "'+str(self.record)+'" var', 1)
        self.assertTrue(self.old_key.exists())
        self.capture(expected=1)

    def test_mount_at_storage_leaf_is_rejected(self):
        mountinfo=self.root/'mountinfo'
        mountinfo.write_text('42 1 0:1 / '+str(self.appdata)+' rw - tmpfs tmpfs rw\n')
        self.functions.write_text(self.functions.read_text().replace('/proc/self/mountinfo',str(mountinfo)))
        self.capture(expected=1)
        self.assertTrue(self.old_key.exists())

    def test_record_permissions_and_extra_lines_are_rejected(self):
        self.capture()
        self.record.chmod(0o666)
        self.sh('package_storage_remove "'+str(self.record)+'" var',1)
        self.record.chmod(0o600)
        self.record.write_text(self.record.read_text()+'unexpected\n')
        self.sh('package_storage_remove "'+str(self.record)+'" var',1)
        self.assertTrue(self.old_key.exists())

    def test_missing_volume_is_not_treated_as_completed_cleanup(self):
        self.prepared(); self.hook('postuninst'); shutil.rmtree(self.base)
        volume=self.root/'volume1';saved=self.root/'unmounted-volume'
        volume.rename(saved);volume.mkdir()
        self.monitor(1)
        self.assertTrue((saved/'@appdata/sadleracme/root/live/key.pem').exists())
        self.assertTrue(self.protected.exists());self.assertTrue((self.removal/'package-var').exists())
        volume.rmdir();saved.rename(volume)
        self.monitor()
        self.assertFalse(self.appdata.exists());self.assertFalse(self.removal.exists())

    def test_changed_parent_identity_is_rejected_even_with_original_leaf(self):
        self.capture()
        original=self.appdata.parent;parked=original.with_name('parked-appdata')
        original.rename(parked);original.mkdir();(parked/'sadleracme').rename(self.appdata)
        self.sh('package_storage_remove "'+str(self.record)+'" var',1)
        self.assertTrue(self.old_key.exists())

    def test_preparation_keeps_backing_data_until_package_gone(self):
        self.prepared()
        self.assertTrue(self.old_key.exists()); self.assertTrue(self.settings.exists())
        self.hook('postuninst')
        self.monitor(33)
        self.assertTrue(self.old_key.exists()); self.assertTrue(self.settings.exists())
        shutil.rmtree(self.base)
        self.monitor()
        self.assertFalse(self.appdata.exists()); self.assertFalse(self.appconf.exists())

    def test_monitor_verifies_all_records_before_first_delete(self):
        self.prepared(); self.hook('postuninst'); shutil.rmtree(self.base)
        original=self.appconf.with_name('original')
        self.appconf.rename(original); self.appconf.mkdir(); (self.appconf/'keep').write_text('keep')
        self.monitor(1)
        self.assertTrue(self.old_key.exists(), 'VAR must survive ETC identity mismatch')
        self.assertTrue(self.protected.exists()); self.assertTrue(self.removal.exists())
        self.assertEqual((self.appconf/'keep').read_text(), 'keep')

    def test_monitor_retry_after_one_backing_directory_already_removed(self):
        self.prepared(); self.hook('postuninst'); shutil.rmtree(self.base)
        shutil.rmtree(self.appdata)
        self.monitor()
        self.assertFalse(self.appconf.exists()); self.assertFalse(self.protected.exists())
        self.assertFalse(self.removal.exists())

    def test_old_preparation_without_storage_records_blocks_uninstall(self):
        self.prepared()
        for name in ('package-var','package-etc'):
            (self.removal/name).unlink()
        self.hook('preuninst',1)
        self.assertTrue(self.old_key.exists()); self.assertTrue(self.settings.exists())

    def test_package_manager_failure_retains_backing_and_restores_hooks(self):
        old=(self.base/'scripts/preuninst').read_text()
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA',expected=1,env={'TEST_PKG_FAIL':'1'})
        self.assertEqual((self.base/'scripts/preuninst').read_text(),old)
        self.assertTrue(self.old_key.exists()); self.assertTrue(self.settings.exists())
        records=list((self.removal/'emergency-storage').iterdir())
        physical=[p for p in records if p.name.startswith(('var.','etc.'))]
        self.assertEqual(len(physical),2, 'Registration symlink and candidate must be deduplicated')
        self.assertTrue((self.removal/'emergency-storage/etc-alias.absent').is_file())

    def fail_rm_at_settings(self):
        self.exe(self.bin/'rm', '#!/bin/sh\nfor item do\n [ "$item" != "'+str(self.appconf)+'" ] || exit 19\ndone\nexec /bin/rm "$@"\n')

    def config_alias(self, target=None):
        alias=self.root/'usr/syno/etc/packages/sadleracme'
        alias.parent.mkdir(parents=True,exist_ok=True)
        alias.symlink_to(str(self.appconf) if target is None else target)
        return alias

    def capture_alias(self, expected=0):
        return self.sh('package_storage_alias_capture "'+str(self.record)+'"',expected)

    def test_config_alias_check_recognises_confirmed_dsm_layout_without_mutating(self):
        alias=self.config_alias()
        shutil.rmtree(self.base);shutil.rmtree(self.protected)
        identity=alias.lstat().st_ino
        p=self.emergency_run('--check')
        self.assertIn(str(alias),p.stdout);self.assertIn(str(self.appconf),p.stdout)
        self.assertNotIn('Unsafe path',p.stdout)
        self.assertEqual(alias.lstat().st_ino,identity)
        self.assertTrue(self.settings.exists());self.assertTrue(self.old_key.exists())
        self.assertFalse(self.removal.exists())

    def test_config_alias_capture_pins_link_and_parents_then_unlinks_only_alias(self):
        alias=self.config_alias()
        self.capture_alias()
        self.assertEqual(self.record.stat().st_mode & 0o777,0o600)
        self.assertEqual(self.record.read_text().splitlines()[0],str(alias))
        self.assertEqual(self.record.read_text().splitlines()[3],str(self.appconf))
        self.sh('package_storage_alias_remove "'+str(self.record)+'"')
        self.assertFalse(alias.is_symlink())
        self.assertTrue(self.settings.exists(),'Alias removal must not traverse the target')

    def test_config_alias_rejects_relative_external_wrong_package_and_chained_targets(self):
        alias=self.config_alias()
        external=self.root/'outside';external.mkdir();(external/'keep').write_text('keep')
        chained=self.root/'volume2/@appconf/sadleracme';chained.parent.mkdir(parents=True)
        chained.symlink_to(self.appconf)
        for target in ('../../../../volume1/@appconf/sadleracme',str(external),
                       str(self.appconf.with_name('other-app')),str(chained)):
            with self.subTest(target=target):
                alias.unlink();alias.symlink_to(target)
                self.capture_alias(expected=1)
                self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA',expected=1)
                self.assertTrue(self.base.exists());self.assertTrue(self.settings.exists())
                self.assertFalse(self.calls.exists(),'Unsafe alias must fail before service/task changes')
        self.assertEqual((external/'keep').read_text(),'keep')

    def test_config_alias_rejects_foreign_link_owner_and_writable_parent(self):
        alias=self.config_alias()
        # Model lstat ownership: this container permits only the root UID.
        self.exe(self.bin/'stat', '#!/bin/sh\nif [ "$1" = -c ] && [ "$2" = %u ] && [ "$3" = "'+str(alias)+'" ]; then echo 1234; else exec /usr/bin/stat "$@"; fi\n')
        self.capture_alias(expected=1)
        (self.bin/'stat').unlink()
        alias.parent.chmod(0o777)
        self.capture_alias(expected=1)
        self.assertTrue(alias.is_symlink());self.assertTrue(self.settings.exists())

    def test_config_alias_replacement_link_is_rejected_even_with_same_target(self):
        alias=self.config_alias();self.capture_alias()
        parked=alias.with_name('saved-link');alias.rename(parked)
        alias.symlink_to(self.appconf)
        self.sh('package_storage_alias_remove "'+str(self.record)+'"',1)
        self.assertTrue(alias.is_symlink());self.assertTrue(self.settings.exists())

    def test_config_alias_parent_replacement_is_rejected_with_original_link(self):
        alias=self.config_alias();self.capture_alias()
        original=alias.parent;parked=original.with_name('saved-packages')
        original.rename(parked);original.mkdir();(parked/'sadleracme').rename(alias)
        self.sh('package_storage_alias_remove "'+str(self.record)+'"',1)
        self.assertTrue(alias.is_symlink());self.assertTrue(self.settings.exists())

    def test_config_alias_target_parent_replacement_is_rejected(self):
        alias=self.config_alias();self.capture_alias()
        original=self.appconf.parent;parked=original.with_name('saved-appconf')
        original.rename(parked);original.mkdir();(parked/'sadleracme').rename(self.appconf)
        self.sh('package_storage_alias_remove "'+str(self.record)+'"',1)
        self.assertTrue(alias.is_symlink());self.assertTrue(self.settings.exists())

    def test_normal_preparation_rejects_config_alias_different_from_registered_etc(self):
        other=self.root/'volume2/@appconf/sadleracme';other.mkdir(parents=True)
        (other/'keep').write_text('keep')
        alias=self.config_alias(other)
        self.sh('prepare_uninstall',1)
        self.assertTrue(self.old_key.exists());self.assertTrue(self.settings.exists())
        self.assertTrue(alias.is_symlink());self.assertEqual((other/'keep').read_text(),'keep')
        self.assertFalse((self.private/'uninstall-ready').exists())

    def test_normal_monitor_removes_backing_data_and_confirmed_config_alias(self):
        alias=self.config_alias();self.prepared()
        self.assertTrue(alias.is_symlink());self.assertTrue(self.settings.exists())
        self.assertTrue((self.removal/'package-etc-alias').exists())
        self.hook('postuninst');shutil.rmtree(self.base)
        self.monitor()
        self.assertFalse(alias.is_symlink());self.assertFalse(self.appconf.exists())
        self.assertFalse(self.appdata.exists());self.assertFalse(self.removal.exists())

    def test_normal_monitor_accepts_dsm_already_removed_captured_alias(self):
        alias=self.config_alias();self.prepared();self.hook('postuninst')
        shutil.rmtree(self.base);alias.unlink()
        self.monitor()
        self.assertFalse(self.appconf.exists());self.assertFalse(self.removal.exists())

    def test_preuninst_requires_alias_manifest_when_dsm_alias_exists(self):
        self.config_alias();self.prepared()
        (self.removal/'package-etc-alias').unlink()
        self.hook('preuninst',1)
        self.assertTrue(self.settings.exists());self.assertTrue(self.old_key.exists())

    def test_normal_monitor_alias_unlink_failure_retains_record_and_retries(self):
        alias=self.config_alias();self.prepared();self.hook('postuninst');shutil.rmtree(self.base)
        self.exe(self.bin/'rm', '#!/bin/sh\nfor item do\n [ "$item" != "'+str(alias)+'" ] || exit 19\ndone\nexec /bin/rm "$@"\n')
        self.monitor(1)
        self.assertFalse(self.appconf.exists());self.assertFalse(self.appdata.exists())
        self.assertTrue(alias.is_symlink());self.assertTrue((self.removal/'package-etc-alias').exists())
        (self.bin/'rm').unlink()
        self.monitor()
        self.assertFalse(alias.is_symlink());self.assertFalse(self.removal.exists())

    def test_normal_monitor_refuses_replaced_or_uncaptured_config_alias_before_data_deletion(self):
        self.prepared();self.hook('postuninst');shutil.rmtree(self.base)
        alias=self.config_alias()
        self.monitor(1)
        self.assertTrue(self.old_key.exists());self.assertTrue(self.settings.exists())
        self.assertTrue(alias.is_symlink())

    def test_normal_monitor_retains_journal_if_alias_appears_during_physical_deletion(self):
        self.prepared();self.hook('postuninst');shutil.rmtree(self.base)
        alias=self.root/'usr/syno/etc/packages/sadleracme';alias.parent.mkdir(parents=True)
        self.exe(self.bin/'rm', '#!/bin/sh\nfor item do\n if [ "$item" = "'+str(self.appconf)+'" ]; then /bin/ln -s "'+str(self.appconf)+'" "'+str(alias)+'"; fi\ndone\nexec /bin/rm "$@"\n')
        self.monitor(1)
        self.assertFalse(self.appconf.exists());self.assertFalse(self.appdata.exists())
        self.assertTrue(alias.is_symlink());self.assertTrue(self.protected.exists())
        self.assertTrue((self.removal/'package-etc-alias.absent').exists())

    def test_emergency_orphan_config_alias_is_deduplicated_and_dsm_certificates_survive(self):
        alias=self.config_alias();shutil.rmtree(self.base);shutil.rmtree(self.protected)
        cert=self.root/'usr/syno/etc/certificate/_archive/fixture/cert.pem'
        cert.parent.mkdir(parents=True);cert.write_text('DSM active certificate')
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA')
        self.assertFalse(alias.is_symlink());self.assertFalse(self.appconf.exists())
        self.assertFalse(self.appdata.exists());self.assertFalse(self.removal.exists())
        self.assertEqual(cert.read_text(),'DSM active certificate')

    def test_emergency_cleans_valid_dangling_config_alias(self):
        alias=self.config_alias();shutil.rmtree(self.base);shutil.rmtree(self.protected)
        shutil.rmtree(self.appdata);shutil.rmtree(self.appconf)
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA')
        self.assertFalse(alias.is_symlink());self.assertFalse(self.removal.exists())

    def test_emergency_imports_normal_alias_record_and_removes_confirmed_data(self):
        alias=self.config_alias();self.prepared()
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA')
        self.assertFalse(alias.is_symlink());self.assertFalse(self.appconf.exists())
        self.assertFalse(self.appdata.exists());self.assertFalse(self.removal.exists())

    def test_emergency_does_not_recapture_replaced_normal_alias(self):
        alias=self.config_alias();self.prepared()
        alias.rename(alias.with_name('saved-link'));alias.symlink_to(self.appconf)
        self.calls.write_text('')
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA',expected=1)
        self.assertEqual(self.calls.read_text(),'')
        self.assertTrue(self.base.exists());self.assertTrue(self.old_key.exists())
        self.assertTrue(self.settings.exists());self.assertTrue(alias.is_symlink())

    def test_emergency_alias_unlink_failure_keeps_record_and_retries_without_recapture(self):
        alias=self.config_alias()
        self.exe(self.bin/'rm', '#!/bin/sh\nfor item do\n [ "$item" != "'+str(alias)+'" ] || exit 19\ndone\nexec /bin/rm "$@"\n')
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA',expected=1)
        self.assertFalse(self.base.exists());self.assertFalse(self.appconf.exists())
        self.assertTrue(alias.is_symlink());self.assertTrue((self.removal/'emergency-storage/etc-alias').exists())
        (self.bin/'rm').unlink()
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA')
        self.assertFalse(alias.is_symlink());self.assertFalse(self.removal.exists())

    def test_emergency_alias_replacement_after_partial_delete_cannot_be_recaptured(self):
        alias=self.config_alias()
        self.fail_rm_at_settings()
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA',expected=1)
        self.assertFalse(self.base.exists());self.assertFalse(self.appdata.exists())
        self.assertTrue(self.settings.exists())
        (self.bin/'rm').unlink()
        alias.rename(alias.with_name('saved-link'));alias.symlink_to(self.appconf)
        self.calls.write_text('')
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA',expected=1)
        self.assertEqual(self.calls.read_text(),'')
        self.assertTrue(self.settings.exists());self.assertTrue(alias.is_symlink())

    def test_emergency_saved_dangling_alias_does_not_capture_new_target_on_retry(self):
        alias=self.config_alias();shutil.rmtree(self.base);shutil.rmtree(self.protected)
        shutil.rmtree(self.appdata);shutil.rmtree(self.appconf)
        self.exe(self.bin/'rm', '#!/bin/sh\nfor item do\n [ "$item" != "'+str(alias)+'" ] || exit 19\ndone\nexec /bin/rm "$@"\n')
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA',expected=1)
        self.assertTrue((self.removal/'emergency-storage/etc-alias').exists())
        (self.bin/'rm').unlink()
        self.appconf.mkdir();(self.appconf/'keep').write_text('new-directory-must-survive')
        self.calls.write_text('')
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA',expected=1)
        self.assertEqual(self.calls.read_text(),'')
        self.assertEqual((self.appconf/'keep').read_text(),'new-directory-must-survive')
        self.assertTrue(alias.is_symlink())

    def test_emergency_saved_absent_alias_refuses_new_alias_on_retry(self):
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA',expected=1,env={'TEST_PKG_FAIL':'1'})
        alias=self.config_alias();self.calls.write_text('')
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA',expected=1)
        self.assertEqual(self.calls.read_text(),'')
        self.assertTrue(self.base.exists());self.assertTrue(self.old_key.exists())
        self.assertTrue(self.settings.exists());self.assertTrue(alias.is_symlink())

    def test_emergency_respects_normal_preparation_absent_alias(self):
        self.prepared();alias=self.config_alias();self.calls.write_text('')
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA',expected=1)
        self.assertEqual(self.calls.read_text(),'')
        self.assertTrue(self.base.exists());self.assertTrue(self.old_key.exists())
        self.assertTrue(self.settings.exists());self.assertTrue(alias.is_symlink())

    def test_monitor_actual_partial_delete_failure_can_retry(self):
        self.prepared(); self.hook('postuninst'); shutil.rmtree(self.base)
        self.fail_rm_at_settings()
        self.monitor(1)
        self.assertFalse(self.appdata.exists()); self.assertTrue(self.settings.exists())
        self.assertTrue(self.protected.exists()); self.assertTrue((self.removal/'package-var').exists())
        (self.bin/'rm').unlink()
        self.monitor()
        self.assertFalse(self.appconf.exists()); self.assertFalse(self.removal.exists())

    def test_emergency_actual_partial_delete_failure_can_retry(self):
        self.fail_rm_at_settings()
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA',expected=1)
        self.assertFalse(self.base.exists()); self.assertFalse(self.appdata.exists())
        self.assertTrue(self.settings.exists()); self.assertTrue((self.removal/'emergency-storage').exists())
        (self.bin/'rm').unlink()
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA')
        self.assertFalse(self.appconf.exists()); self.assertFalse(self.removal.exists())

    def test_emergency_retry_refuses_changed_saved_identity(self):
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA',expected=1,env={'TEST_PKG_FAIL':'1'})
        original=self.appdata.with_name('original')
        self.appdata.rename(original); self.appdata.mkdir(); (self.appdata/'keep').write_text('keep')
        self.calls.write_text('')
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA',expected=1)
        self.assertEqual((self.appdata/'keep').read_text(),'keep')
        self.assertEqual(self.calls.read_text(),'')
        self.assertTrue(self.base.exists()); self.assertTrue(self.settings.exists())

    def test_emergency_respects_normal_preparation_original_identity(self):
        self.prepared()
        original=self.appdata.with_name('original')
        self.appdata.rename(original); self.appdata.mkdir(); (self.appdata/'keep').write_text('keep')
        self.calls.write_text('')
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA',expected=1)
        self.assertEqual(self.calls.read_text(),'')
        self.assertTrue((original/'root/live/key.pem').exists())
        self.assertEqual((self.appdata/'keep').read_text(),'keep')
        self.assertTrue(self.settings.exists())

    def fresh_package_owner_fixture(self):
        # The test runner maps only UID 0. Model ownership queries by inode;
        # real files, symlink behavior and removal ordering remain exercised.
        shutil.rmtree(self.protected)
        shutil.rmtree(self.appdata/'root')
        self.owners=self.root/'package-owners.json'
        self.refresh_package_owners()
        self.exe(self.bin/'id', '#!/bin/sh\ncase "$1" in -u) echo 65534;; -un) echo sadleracme;; *) exec /usr/bin/id "$@";; esac\n')
        self.exe(self.bin/'stat', '''#!/usr/bin/python3
import json,os,sys
from pathlib import Path
args=sys.argv[1:]
if len(args)==3 and args[0] in ('-c','-Lc') and args[1]=='%u':
 value=os.stat(args[2],follow_symlinks=args[0]=='-Lc')
 owners=json.loads(Path(os.environ['TEST_OWNERS']).read_text())
 print(owners.get(str(value.st_dev)+':'+str(value.st_ino),value.st_uid))
else:os.execv('/usr/bin/stat',['stat']+args)
''')
        self.exe(self.bin/'find', '''#!/usr/bin/python3
import json,os,sys
from pathlib import Path
args=sys.argv[1:]
if '! -user' not in ' '.join(args):os.execv('/usr/bin/find',['find']+args)
expected=int(args[args.index('-user')+1]); owners=json.loads(Path(os.environ['TEST_OWNERS']).read_text())
for parent,dirs,files in os.walk(args[0],followlinks=False):
 for name in dirs+files:
  path=Path(parent)/name; value=path.lstat()
  if owners.get(str(value.st_dev)+':'+str(value.st_ino),value.st_uid)!=expected:print(path)
''')
        self.env['TEST_OWNERS']=str(self.owners)

    def refresh_package_owners(self):
        owners={}
        for root in (self.appdata,self.appconf):
            for path in [root]+list(root.rglob('*')):
                value=path.lstat();owners[str(value.st_dev)+':'+str(value.st_ino)]=65534
        self.owners.write_text(json.dumps(owners))

    def test_fresh_hook_clears_package_owned_contents_keeps_dsm_leaf(self):
        self.fresh_package_owner_fixture()
        other=self.appdata.with_name('other-app');other.mkdir();(other/'keep').write_text('keep')
        outside=self.root/'outside';outside.mkdir();(outside/'keep').write_text('keep')
        (self.appdata/'link-outside').symlink_to(outside)
        self.refresh_package_owners()
        self.hook('preuninst')
        self.hook('postuninst')
        self.assertEqual(list(self.appdata.iterdir()),[])
        self.assertEqual(list(self.appconf.iterdir()),[])
        self.assertEqual((other/'keep').read_text(),'keep')
        self.assertEqual((outside/'keep').read_text(),'keep')

    def test_fresh_hook_refuses_root_execution(self):
        shutil.rmtree(self.protected)
        shutil.rmtree(self.appdata/'root')
        self.hook('postuninst',1)
        self.assertTrue(self.settings.exists())

    def test_fresh_hook_validates_both_trees_before_first_delete(self):
        self.fresh_package_owner_fixture()
        owners=json.loads(self.owners.read_text());value=self.settings.stat()
        del owners[str(value.st_dev)+':'+str(value.st_ino)]
        self.owners.write_text(json.dumps(owners))
        self.hook('postuninst',1)
        self.assertTrue((self.appdata/'package.running').exists())
        self.assertTrue(self.settings.exists())

    def test_fresh_hook_retains_legacy_root_directory(self):
        self.fresh_package_owner_fixture()
        (self.appdata/'root').mkdir();(self.appdata/'root/key.pem').write_text('keep')
        self.refresh_package_owners()
        self.hook('preuninst',1)
        self.hook('postuninst',1)
        self.assertEqual((self.appdata/'root/key.pem').read_text(),'keep')
        self.assertTrue(self.settings.exists())

    def test_emergency_check_reports_orphan_storage_without_mutating(self):
        shutil.rmtree(self.base); shutil.rmtree(self.protected)
        p=self.emergency_run('--check')
        self.assertIn(str(self.appdata), p.stdout)
        self.assertIn(str(self.appconf), p.stdout)
        self.assertNotIn('fixture-private-key', p.stdout+p.stderr)
        self.assertNotIn('fixture-cloudflare-token', p.stdout+p.stderr)
        self.assertTrue(self.old_key.exists()); self.assertTrue(self.settings.exists())

    def test_emergency_removes_orphan_storage_only(self):
        shutil.rmtree(self.base); shutil.rmtree(self.protected)
        other=self.appdata.with_name('other-app');other.mkdir();(other/'keep').write_text('keep')
        unit=self.units/'other-app.service';unit.write_text('keep')
        cert=self.root/'usr/syno/etc/certificate/_archive/fixture/cert.pem'
        cert.parent.mkdir(parents=True);cert.write_text('DSM active certificate')
        self.emergency_run('--remove','--confirm','REMOVE SADLERACME DATA')
        self.assertFalse(self.appdata.exists());self.assertFalse(self.appconf.exists())
        self.assertEqual((other/'keep').read_text(),'keep');self.assertEqual(unit.read_text(),'keep')
        self.assertEqual(cert.read_text(),'DSM active certificate')

    def test_emergency_unsafe_storage_rejected_before_task_deletion(self):
        tasks=self.root/'tasks';tasks.write_text('SadlerACME Setup|0|/bin/systemctl start pkg-sadleracme-setup.service|script')
        original=self.appdata.with_name('original');self.appdata.rename(original);self.appdata.symlink_to(original)
        self.emergency_run('--remove','--remove-tasks','--confirm','REMOVE SADLERACME DATA',expected=1,env={'TEST_TASKS_FILE':str(tasks)})
        self.assertIn('SadlerACME Setup',tasks.read_text())
        self.assertFalse(self.calls.exists())
        self.assertTrue((original/'root/live/key.pem').exists())


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(PackageStorage(name) for name in sorted(PackageStorage.__dict__) if name.startswith('test_'))

if __name__ == '__main__':
    unittest.main(verbosity=2)
