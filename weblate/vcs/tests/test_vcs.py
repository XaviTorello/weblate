# -*- coding: utf-8 -*-
#
# Copyright © 2012 - 2019 Michal Čihař <michal@cihar.com>
#
# This file is part of Weblate <https://weblate.org/>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#

from __future__ import unicode_literals

import os.path
import shutil
import tempfile
from unittest import SkipTest

from django.test import TestCase
from django.test.utils import override_settings
from django.utils import timezone

from weblate.trans.tests.utils import RepoTestMixin, TempDirMixin, get_test_file
from weblate.utils.files import remove_readonly
from weblate.vcs.base import RepositoryException
from weblate.vcs.git import (
    GitForcePushRepository,
    GithubRepository,
    GitlabRepository,
    GitRepository,
    GitWithGerritRepository,
    LocalRepository,
    SubversionRepository,
)
from weblate.vcs.mercurial import HgRepository


class GithubFakeRepository(GithubRepository):
    _is_supported = None
    _version = None
    _cmd = get_test_file('hub')


class GitlabFakeRepository(GitlabRepository):
    _is_supported = None
    _version = None
    _cmd = get_test_file('lab')


class GitTestRepository(GitRepository):
    _is_supported = None
    _version = None


class NonExistingRepository(GitRepository):
    _is_supported = None
    _version = None
    _cmd = 'nonexisting-command'


class GitVersionRepository(GitRepository):
    _is_supported = None
    _version = None
    req_version = '200000'


class GitNoVersionRepository(GitRepository):
    _is_supported = None
    _version = None
    req_version = None


class RepositoryTest(TestCase):
    def test_not_supported(self):
        self.assertFalse(NonExistingRepository.is_supported())

    def test_not_supported_version(self):
        self.assertFalse(GitVersionRepository.is_supported())

    def test_is_supported(self):
        self.assertTrue(GitTestRepository.is_supported())

    def test_is_supported_no_version(self):
        self.assertTrue(GitNoVersionRepository.is_supported())

    def test_is_supported_cache(self):
        GitTestRepository.is_supported()
        self.assertTrue(GitTestRepository.is_supported())


class VCSGitTest(TestCase, RepoTestMixin, TempDirMixin):
    _class = GitRepository
    _vcs = 'git'
    _sets_push = True
    _remote_branches = ['master', 'translations']

    def setUp(self):
        super(VCSGitTest, self).setUp()
        if not self._class.is_supported():
            raise SkipTest('Not supported')

        self.clone_test_repos()

        self.create_temp()
        self.repo = self.clone_repo(self.tempdir)
        self.fixup_repo(self.repo)

    def fixup_repo(self, repo):
        return

    def clone_repo(self, path):
        return self._class.clone(
            self.format_local_path(getattr(self, '{0}_repo_path'.format(self._vcs))),
            path,
        )

    def tearDown(self):
        self.remove_temp()

    def add_remote_commit(self, conflict=False, rename=False):
        tempdir = tempfile.mkdtemp()
        try:
            repo = self.clone_repo(tempdir)
            self.fixup_repo(repo)

            with repo.lock:
                repo.set_committer('Second Bar', 'second@example.net')
                if rename:
                    shutil.move(
                        os.path.join(tempdir, 'README.md'),
                        os.path.join(tempdir, 'READ ME.md'),
                    )
                    if self._vcs == 'mercurial':
                        repo.remove(['README.md'], 'Removed readme')
                        filenames = ['READ ME.md']
                    else:
                        filenames = None
                else:
                    if conflict:
                        filename = 'testfile'
                    else:
                        filename = 'test2'
                    # Create test file
                    with open(os.path.join(tempdir, filename), 'w') as handle:
                        handle.write('SECOND TEST FILE\n')
                    filenames = [filename]

                # Commit it
                repo.commit(
                    'Test commit', 'Foo Bar <foo@bar.com>', timezone.now(), filenames
                )

                # Push it
                repo.push()
        finally:
            shutil.rmtree(tempdir, onerror=remove_readonly)

    def test_clone(self):
        # Verify that VCS directory exists
        if self._vcs == 'mercurial':
            dirname = '.hg'
        elif self._vcs == 'local':
            dirname = '.git'
        else:
            dirname = '.{}'.format(self._vcs)
        self.assertTrue(os.path.exists(os.path.join(self.tempdir, dirname)))

    def test_revision(self):
        self.assertEqual(self.repo.last_revision, self.repo.last_remote_revision)

    def test_update_remote(self):
        with self.repo.lock:
            self.repo.update_remote()

    def test_push(self):
        with self.repo.lock:
            self.repo.push()

    def test_push_commit(self):
        self.test_commit()
        self.test_push()

    def test_reset(self):
        with self.repo.lock:
            original = self.repo.last_revision
            self.repo.reset()
            self.assertEqual(original, self.repo.last_revision)
        self.test_commit()
        with self.repo.lock:
            self.assertNotEqual(original, self.repo.last_revision)
            self.repo.reset()
            self.assertEqual(original, self.repo.last_revision)

    def test_cleanup(self):
        with self.repo.lock:
            self.repo.cleanup()

    def test_merge_commit(self):
        self.test_commit()
        self.test_merge()

    def test_rebase_commit(self):
        self.test_commit()
        self.test_rebase()

    def test_merge_remote(self):
        self.add_remote_commit()
        self.test_merge()

    def test_rebase_remote(self):
        self.add_remote_commit()
        self.test_rebase()

    def test_merge_both(self):
        self.add_remote_commit()
        self.test_commit()
        self.test_merge()

    def test_rebase_both(self):
        self.add_remote_commit()
        self.test_commit()
        self.test_rebase()

    def test_merge_conflict(self):
        self.add_remote_commit(conflict=True)
        self.test_commit()
        with self.assertRaises(RepositoryException):
            self.test_merge()

    def test_rebase_conflict(self):
        self.add_remote_commit(conflict=True)
        self.test_commit()
        with self.assertRaises(RepositoryException):
            self.test_rebase()

    def test_upstream_changes(self):
        self.add_remote_commit()
        with self.repo.lock:
            self.repo.update_remote()
        self.assertEqual(['test2'], self.repo.list_upstream_changed_files())

    def test_upstream_changes_rename(self):
        self.add_remote_commit(rename=True)
        with self.repo.lock:
            self.repo.update_remote()
        self.assertEqual(
            ['README.md', 'READ ME.md'], self.repo.list_upstream_changed_files()
        )

    def test_merge(self):
        self.test_update_remote()
        with self.repo.lock:
            self.repo.merge()

    def test_rebase(self):
        self.test_update_remote()
        with self.repo.lock:
            self.repo.rebase()

    def test_status(self):
        status = self.repo.status()
        # Older git print up-to-date, newer up to date
        self.assertIn("date with 'origin/master'.", status)

    def test_needs_commit(self):
        self.assertFalse(self.repo.needs_commit())
        with open(os.path.join(self.tempdir, 'README.md'), 'a') as handle:
            handle.write('CHANGE')
        self.assertTrue(self.repo.needs_commit())
        self.assertTrue(self.repo.needs_commit('README.md'))
        self.assertFalse(self.repo.needs_commit('dummy'))

    def check_valid_info(self, info):
        self.assertTrue('summary' in info)
        self.assertNotEqual(info['summary'], '')
        self.assertTrue('author' in info)
        self.assertNotEqual(info['author'], '')
        self.assertTrue('authordate' in info)
        self.assertNotEqual(info['authordate'], '')
        self.assertTrue('commit' in info)
        self.assertNotEqual(info['commit'], '')
        self.assertTrue('commitdate' in info)
        self.assertNotEqual(info['commitdate'], '')
        self.assertTrue('revision' in info)
        self.assertNotEqual(info['revision'], '')
        self.assertTrue('shortrevision' in info)
        self.assertNotEqual(info['shortrevision'], '')

    def test_revision_info(self):
        # Latest commit
        info = self.repo.get_revision_info(self.repo.last_revision)
        self.check_valid_info(info)

    def test_needs_merge(self):
        self.assertFalse(self.repo.needs_merge())
        self.assertFalse(self.repo.needs_push())

    def test_needs_push(self):
        self.test_commit()
        self.assertTrue(self.repo.needs_push())

    def test_is_supported(self):
        self.assertTrue(self._class.is_supported())

    def test_get_version(self):
        self.assertNotEqual(self._class.get_version(), '')

    def test_set_committer(self):
        with self.repo.lock:
            self.repo.set_committer('Foo Bar Žač', 'foo@example.net')
        self.assertEqual(self.repo.get_config('user.name'), 'Foo Bar Žač')
        self.assertEqual(self.repo.get_config('user.email'), 'foo@example.net')

    def test_commit(self, committer='Foo Bar'):
        committer_email = '{} <foo@example.com>'.format(committer)
        with self.repo.lock:
            self.repo.set_committer(committer, 'foo@example.net')
        # Create test file
        with open(os.path.join(self.tempdir, 'testfile'), 'wb') as handle:
            handle.write(b'TEST FILE\n')

        oldrev = self.repo.last_revision
        # Commit it
        with self.repo.lock:
            self.repo.commit(
                'Test commit', committer_email, timezone.now(), ['testfile']
            )
        # Check we have new revision
        self.assertNotEqual(oldrev, self.repo.last_revision)
        info = self.repo.get_revision_info(self.repo.last_revision)
        self.assertEqual(info['author'], committer_email)

        # Check file hash
        self.assertEqual(
            self.repo.get_object_hash('testfile'),
            'fafd745150eb1f20fc3719778942a96e2106d25b',
        )

        # Check invalid commit
        with self.repo.lock, self.assertRaises(RepositoryException):
            self.repo.commit('test commit', committer_email)

    def test_commit_unicode(self):
        self.test_commit('Zkouška Sirén')

    def test_remove(self):
        with self.repo.lock:
            self.repo.set_committer('Foo Bar', 'foo@example.net')
        self.assertTrue(os.path.exists(os.path.join(self.tempdir, 'po/cs.po')))
        with self.repo.lock:
            self.repo.remove(['po/cs.po'], 'Remove Czech translation')
        self.assertFalse(os.path.exists(os.path.join(self.tempdir, 'po/cs.po')))

    def test_object_hash(self):
        obj_hash = self.repo.get_object_hash('README.md')
        self.assertEqual(len(obj_hash), 40)

    def test_configure_remote(self):
        with self.repo.lock:
            self.repo.configure_remote('pullurl', 'pushurl', 'branch')
            self.assertEqual(self.repo.get_config('remote.origin.url'), 'pullurl')
            if self._sets_push:
                self.assertEqual(
                    self.repo.get_config('remote.origin.pushURL'), 'pushurl'
                )
            # Test that we handle not set fetching
            self.repo.execute(['config', '--unset', 'remote.origin.fetch'])
            self.repo.configure_remote('pullurl', 'pushurl', 'branch')
            self.assertEqual(
                self.repo.get_config('remote.origin.fetch'),
                '+refs/heads/*:refs/remotes/origin/*',
            )

    def test_configure_remote_no_push(self):
        with self.repo.lock:
            if self._sets_push:
                self.repo.configure_remote('pullurl', '', 'branch')
                self.assertEqual(self.repo.get_config('remote.origin.pushURL'), '')
                self.repo.configure_remote('pullurl', 'push', 'branch')
                self.assertEqual(self.repo.get_config('remote.origin.pushURL'), 'push')

    def test_configure_branch(self):
        # Existing branch
        with self.repo.lock:
            self.repo.configure_branch(self._class.default_branch)

            with self.assertRaises(RepositoryException):
                self.repo.configure_branch('branch')

    def test_get_file(self):
        self.assertIn('msgid', self.repo.get_file('po/cs.po', self.repo.last_revision))

    def test_remote_branches(self):
        self.assertEqual(self._remote_branches, self.repo.list_remote_branches())


class VCSGitForcePushTest(VCSGitTest):
    _class = GitForcePushRepository


class VCSGerritTest(VCSGitTest):
    _class = GitWithGerritRepository
    _vcs = 'git'

    def fixup_repo(self, repo):
        # Create commit-msg hook, so that git-review doesn't try
        # to create one
        hook = os.path.join(repo.path, '.git', 'hooks', 'commit-msg')
        with open(hook, 'w') as handle:
            handle.write('#!/bin/sh\nexit 0\n')
        os.chmod(hook, 0o755)

    def add_remote_commit(self, conflict=False, rename=False):
        # Use Git to create changed upstream repo
        self._class = GitRepository
        try:
            super(VCSGerritTest, self).add_remote_commit(conflict, rename)
        finally:
            self._class = GitWithGerritRepository


@override_settings(GITHUB_USERNAME="test")
class VCSGithubTest(VCSGitTest):
    _class = GithubFakeRepository
    _vcs = 'git'
    _sets_push = False


@override_settings(GITLAB_USERNAME="test")
class VCSGitlabTest(VCSGitTest):
    _class = GitlabFakeRepository
    _vcs = 'git'
    _sets_push = False


class VCSSubversionTest(VCSGitTest):
    _class = SubversionRepository
    _vcs = 'subversion'
    _remote_branches = []

    def test_clone(self):
        self.assertTrue(os.path.exists(os.path.join(self.tempdir, '.git', 'svn')))

    def test_revision_info(self):
        # Latest commit
        info = self.repo.get_revision_info(self.repo.last_revision)
        self.check_valid_info(info)

    def test_status(self):
        status = self.repo.status()
        self.assertIn('nothing to commit', status)

    def test_configure_remote(self):
        with self.repo.lock:
            with self.assertRaises(RepositoryException):
                self.repo.configure_remote('pullurl', 'pushurl', 'branch')
        self.verify_pull_url()

    def test_configure_remote_no_push(self):
        with self.repo.lock:
            self.repo.configure_remote(
                self.format_local_path(self.subversion_repo_path),
                self.format_local_path(self.subversion_repo_path),
                'master',
            )
            with self.assertRaises(RepositoryException):
                self.repo.configure_remote('pullurl', '', 'branch')
        self.verify_pull_url()

    def verify_pull_url(self):
        self.assertEqual(
            self.repo.get_config('svn-remote.svn.url'),
            self.format_local_path(self.subversion_repo_path),
        )


class VCSSubversionBranchTest(VCSSubversionTest):
    """Cloning subversion branch directly."""

    def clone_test_repos(self):
        super(VCSSubversionBranchTest, self).clone_test_repos()
        self.subversion_repo_path += '/trunk'


class VCSHgTest(VCSGitTest):
    """
    Mercurial repository testing.
    """

    _class = HgRepository
    _vcs = 'mercurial'
    _remote_branches = []

    def test_configure_remote(self):
        with self.repo.lock:
            self.repo.configure_remote('/pullurl', '/pushurl', 'branch')
        self.assertEqual(self.repo.get_config('paths.default'), '/pullurl')
        self.assertEqual(self.repo.get_config('paths.default-push'), '/pushurl')

    def test_configure_remote_no_push(self):
        with self.repo.lock:
            self.repo.configure_remote('/pullurl', '', 'branch')
        self.assertEqual(self.repo.get_config('paths.default-push'), '')
        with self.repo.lock:
            self.repo.configure_remote('/pullurl', '/push', 'branch')
        self.assertEqual(self.repo.get_config('paths.default-push'), '/push')

    def test_revision_info(self):
        # Latest commit
        info = self.repo.get_revision_info(self.repo.last_revision)
        self.check_valid_info(info)

    def test_set_committer(self):
        with self.repo.lock:
            self.repo.set_committer('Foo Bar Žač', 'foo@example.net')
        self.assertEqual(
            self.repo.get_config('ui.username'), 'Foo Bar Žač <foo@example.net>'
        )

    def test_status(self):
        status = self.repo.status()
        self.assertEqual(status, '')


class VCSLocalTest(VCSGitTest):
    """
    Local repository testing.
    """

    _class = LocalRepository
    _vcs = 'local'
    _remote_branches = []

    @classmethod
    def setUpClass(cls):
        super(VCSLocalTest, cls).setUpClass()
        # Global setup to configure git committer
        GitRepository.global_setup()

    def test_status(self):
        status = self.repo.status()
        # Older git print up-to-date, newer up to date
        self.assertIn("On branch master", status)

    def test_upstream_changes(self):
        raise SkipTest('Not supported')

    def test_upstream_changes_rename(self):
        raise SkipTest('Not supported')

    def test_get_file(self):
        raise SkipTest('Not supported')

    def test_remove(self):
        raise SkipTest('Not supported')

    def test_needs_push(self):
        self.test_commit()
        self.assertFalse(self.repo.needs_push())

    def test_reset(self):
        raise SkipTest('Not supported')

    def test_merge_conflict(self):
        raise SkipTest('Not supported')

    def test_rebase_conflict(self):
        raise SkipTest('Not supported')

    def test_configure_remote(self):
        raise SkipTest('Not supported')

    def test_configure_remote_no_push(self):
        raise SkipTest('Not supported')
