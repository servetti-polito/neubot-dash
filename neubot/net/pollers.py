# neubot/net/pollers.py
# Copyright (c) 2010 NEXA Center for Internet & Society

# This file is part of Neubot.
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
# Poll() and dispatch I/O events (such as "socket readable")
#

from select import error
from neubot.utils import unit_formatter
from neubot.utils import ticks
from select import select
from sys import stdout
from errno import EINTR
from neubot import log

# Base class for every socket managed by the poller
class Pollable:
    def fileno(self):
        raise NotImplementedError

    def readable(self):
        pass

    def writable(self):
        pass

    def readtimeout(self, now):
        return False

    def writetimeout(self, now):
        return False

    def closing(self):
        pass

class PollerTask:
    def __init__(self, time, func, periodic, delta):
        self.time = time
        self.func = func
        self.periodic = periodic
        self.delta = delta

# Interval between each check for timed-out I/O operations
CHECK_TIMEOUT = 10

class SimpleStats:
    def __init__(self):
        self.begin()

    def begin(self):
        self.start = ticks()
        self.stop = 0
        self.length = 0

    def end(self):
        self.stop = ticks()

    def account(self, count):
        self.length += count

    def diff(self):
        return self.stop - self.start

    def speed(self):
        return self.length / self.diff()

class Stats:
    def __init__(self):
        self.send = SimpleStats()
        self.recv = SimpleStats()

class Poller:
    def __init__(self, timeout, get_ticks):
        self.timeout = timeout
        self.get_ticks = get_ticks
        self.printstats = False
        self.readset = {}
        self.writeset = {}
        self.pending = []
        self.registered = {}
        self.tasks = []
        self.sched(CHECK_TIMEOUT, self.check_timeout)
        self.stats = Stats()
        self.sched(1, self._update_stats)

    def __del__(self):
        pass

    #
    # Unsched() does not remove a task, but it just marks it as "dead",
    # and this means that (a) it sets its func member to None, and (b)
    # its time to -1.  The (a) step breks the reference from the task
    # to the object that registered the task (and so the object could
    # possibly be collected).  The (b) step causes the dead task to be
    # moved at the beginning of the list, and we do that because we
    # don't want a dead task to linger in the list for some time (in
    # other words we optimize for memory rather than for speed).
    # XXX Throughout the scheduler code we employ func() as if it was
    # unique, but this is True for bound functions only!
    #

    def sched(self, delta, func, periodic=False):
        if self.registered.has_key(func):
            task = self.registered[func]
            task.time = self.get_ticks() + delta
            task.periodic = periodic
        else:
            task = PollerTask(self.get_ticks()+delta,func,periodic,delta)
            self.pending.append(task)

    def unsched(self, delta, func, periodic=False):
        if self.registered.has_key(func):
            task = self.registered[func]
            task.func = None
            task.time = -1
            del self.registered[func]
        else:
            for task in self.pending:
                if task.func == func:
                    # delete while pending
                    task.func = None
                    task.time = -1

    #
    # BEGIN deprecated functions
    # Use the sched() / unsched() interface instead

    def register_periodic(self, periodic):
        log.debug("register_periodic() is deprecated")
        self.sched(self.timeout, periodic, True)

    def unregister_periodic(self, periodic):
        log.debug("unregister_periodic() is deprecated")
        self.unsched(self.timeout, periodic, True)

    # END deprecated functions
    #

    def set_readable(self, stream):
        self.readset[stream.fileno()] = stream

    def set_writable(self, stream):
        self.writeset[stream.fileno()] = stream

    def unset_readable(self, stream):
        fileno = stream.fileno()
        if self.readset.has_key(fileno):
            del self.readset[fileno]

    def unset_writable(self, stream):
        fileno = stream.fileno()
        if self.writeset.has_key(fileno):
            del self.writeset[fileno]

    def close(self, stream):
        self.unset_readable(stream)
        self.unset_writable(stream)
        stream.closing()

    #
    # We are very careful when accessing readset and writeset because
    # it's possible that the fileno makes reference to a stream that
    # does not exist anymore.  Consider the following example: There is
    # a stream that is both readable and writable, and so its fileno
    # is both in res[0] and res[1].  But, when we invoke the stream's
    # readable() callback there is a protocol violation and so the
    # high-level code invokes close(), and the stream is closed, and
    # hence removed from readset and writeset.  And then the stream
    # does not exist anymore, but its fileno still is in res[1].
    #

    def _readable(self, fileno):
        if self.readset.has_key(fileno):
            stream = self.readset[fileno]
            try:
                stream.readable()
            except KeyboardInterrupt:
                raise
            except:
                log.exception()
                self.close(stream)

    def _writable(self, fileno):
        if self.writeset.has_key(fileno):
            stream = self.writeset[fileno]
            try:
                stream.writable()
            except KeyboardInterrupt:
                raise
            except:
                log.exception()
                self.close(stream)

    #
    # Welcome to the core loop.
    #
    # Probably the core loop was faster when it was just
    # one single complex function, but written in this
    # way it is simpler to deal with reference counting
    # issues.
    # If there aren't readable or writable filenos we break
    # the loop, regardless of the scheduled tasks.  And this
    # happens because: (i) neubot is not ready to do everything
    # inside the poller loop(), and it assumes that the loop
    # will break as soon as I/O is complete; and (ii) there
    # are some tasks that re-schedule self forever, like the
    # one of neubot/notify.py.
    #

    def loop(self):
        while self.readset or self.writeset:
            self.update_tasks()
            self.dispatch_events()

    def dispatch(self):
        if self.readset or self.writeset:
            self.update_tasks()
            self.dispatch_events()

    #
    # Tests shows that update_tasks() would be slower if we kept tasks
    # sorted in reverse order--yes, with this arrangement it would be
    # faster to delete elements (because it would be just a matter of
    # shrinking the list), but the sort would be slower, and, our tests
    # suggest that we loose more with the sort than we gain with the
    # delete.
    #

    def update_tasks(self):
        now = self.get_ticks()
        if self.pending:
            for task in self.pending:
                if task.time == -1 or task.func == None:
                    # deleted while pending
                    continue
                self.tasks.append(task)
                self.registered[task.func] = task
            self.pending = []
        if self.tasks:
            self.tasks.sort(key=lambda task: task.time)
            index = 0
            for task in self.tasks:
                if task.time > 0:
                    if task.time > now:
                        break
                    if task.func:                       # redundant
                        del self.registered[task.func]
                        if task.periodic:
                            try:
                                task.func(now)
                            except KeyboardInterrupt:
                                raise
                            except:
                                log.exception()
                            self.sched(task.delta, task.func, True)
                        else:
                            try:
                                task.func()
                            except KeyboardInterrupt:
                                raise
                            except:
                                log.exception()
                index = index + 1
            del self.tasks[:index]

    def dispatch_events(self):
        if self.readset or self.writeset:
            try:
                res = select(self.readset.keys(), self.writeset.keys(),
                 [], self.timeout)
            except error, (code, reason):
                if code != EINTR:
                    log.exception()
                    raise
            else:
                for fileno in res[0]:
                    self._readable(fileno)
                for fileno in res[1]:
                    self._writable(fileno)

    def check_timeout(self):
        self.sched(CHECK_TIMEOUT, self.check_timeout)
        if self.readset or self.writeset:
            now = self.get_ticks()
            x = self.readset.values()
            for stream in x:
                if stream.readtimeout(now):
                    self.close(stream)
            x = self.writeset.values()
            for stream in x:
                if stream.writetimeout(now):
                    self.close(stream)

    def disable_stats(self):
        if self.printstats:
            stdout.write("\n")
        self.printstats = False

    def enable_stats(self):
        self.printstats = True

    def _update_stats(self):
        self.sched(1, self._update_stats)
        if self.printstats:
            # send
            self.stats.send.end()
            send = self.stats.send.speed()
            self.stats.send.begin()
            # recv
            self.stats.recv.end()
            recv = self.stats.recv.speed()
            self.stats.recv.begin()
            # print
            stats = "\r    send: %s | recv: %s" % (
             unit_formatter(send, unit="B/s"),
             unit_formatter(recv, unit="B/s"))
            if len(stats) < 80:
                stats += " " * (80 - len(stats))
            stdout.write(stats)
            stdout.flush()

poller = Poller(1, ticks)

dispatch = poller.dispatch
loop = poller.loop
register_periodic = poller.register_periodic
sched = poller.sched
unsched = poller.unsched
unregister_periodic = poller.unregister_periodic
disable_stats = poller.disable_stats
enable_stats = poller.enable_stats
