# neubot/poller.py

#
# Copyright (c) 2012 Simone Basso <bassosimone@gmail.com>,
#  NEXA Center for Internet & Society at Politecnico di Torino
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

''' Dispatch read, write, periodic and other events '''

# Will be replaced by neubot/poller.py

from neubot.poller import POLLER
from neubot.utils import ticks

#
# The default watchdog timeout is positive and large
# because we don't want by mistake that something runs
# forever.  Who needs to do that should override it.
#
WATCHDOG = 300

class Pollable(object):

    ''' Base class for pollable objects '''

    def __init__(self):
        ''' Initialize '''
        self.created = ticks()
        self.watchdog = WATCHDOG

    def fileno(self):
        ''' Return file number '''
        raise NotImplementedError

    def handle_read(self):
        ''' Invoked to handle the read event '''

    def handle_write(self):
        ''' Invoked to handle the write event '''

    def handle_close(self):
        ''' Invoked to handle the close event '''

    def handle_periodic(self, timenow):
        ''' Invoked to handle the periodic event '''
        return self.watchdog >= 0 and timenow - self.created > self.watchdog
