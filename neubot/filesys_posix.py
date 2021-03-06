# neubot/filesys_posix.py

#
# Copyright (c) 2012
#     Nexa Center for Internet & Society, Politecnico di Torino (DAUIN)
#     and Simone Basso <bassosimone@gmail.com>
#
# This file is part of Neubot <http://www.neubot.org/>.
#
# Neubot is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Neubot is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Neubot.  If not, see <http://www.gnu.org/licenses/>.
#

''' POSIX filesystem '''

import getopt
import logging
import sys

if __name__ == '__main__':
    sys.path.insert(0, '.')

from neubot.config import CONFIG

from neubot import system_posix
from neubot import utils_posix
from neubot import utils_path
from neubot import utils_hier

class FileSystemPOSIX(object):
    ''' POSIX file system '''

    def __init__(self):
        ''' Init POSIX filesystem '''
        self.datadir = None
        self.passwd = None

    def datadir_init(self, uname=None, datadir=None):
        ''' Initialize datadir '''

        if datadir:
            self.datadir = datadir
        else:
            self.datadir = utils_hier.LOCALSTATEDIR
        logging.debug('filesys_posix: datadir: %s', self.datadir)

        logging.debug('filesys_posix: user name: %s', uname)
        if uname:
            self.passwd = utils_posix.getpwnam(uname)
        else:
            self.passwd = system_posix.getpwnam()  # The common case
        logging.debug('filesys_posix: uid: %d', self.passwd.pw_uid)
        logging.debug('filesys_posix: gid: %d', self.passwd.pw_gid)

        #
        # Here we are assuming that /var (BSD) or /var/lib (Linux)
        # exists and has the correct permissions.
        # We are also assuming that we are running with enough privs
        # to be able to create a directory there on behalf of the
        # specified uid and gid.
        #
        logging.debug('filesys_posix: datadir init: %s', self.datadir)
        utils_posix.mkdir_idempotent(self.datadir, self.passwd.pw_uid,
                                     self.passwd.pw_gid)

    def datadir_touch(self, components):
        ''' Touch a file below datadir '''
        return utils_path.depth_visit(self.datadir, components, self._visit)

    def _visit(self, curpath, leaf):
        ''' Callback for depth_visit() '''
        if not leaf:
            logging.debug('filesys_posix: mkdir_idempotent: %s', curpath)
            utils_posix.mkdir_idempotent(curpath, self.passwd.pw_uid,
                                         self.passwd.pw_gid)
        else:
            logging.debug('filesys_posix: touch_idempotent: %s', curpath)
            utils_posix.touch_idempotent(curpath, self.passwd.pw_uid,
                                         self.passwd.pw_gid)

USAGE = 'Usage: filesys_posix.py [-v] [-d datadir] [-u user] component...'

def main(args):
    ''' main function '''

    try:
        options, arguments = getopt.getopt(args[1:], 'd:u:v')
    except getopt.error:
        sys.exit(USAGE)
    if len(arguments) == 0:
        sys.exit(USAGE)

    datadir = None
    uname = None
    for name, value in options:
        if name == '-d':
            datadir = value
        elif name == '-u':
            uname = value
        elif name == '-v':
            CONFIG['verbose'] = 1

    filesys = FileSystemPOSIX()
    filesys.datadir_init(uname, datadir)
    filesys.datadir_touch(arguments)

if __name__ == '__main__':
    main(sys.argv)
