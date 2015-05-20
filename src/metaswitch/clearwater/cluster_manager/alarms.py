# @file alarms.py
#
# Project Clearwater - IMS in the Cloud
# Copyright (C) 2014  Metaswitch Networks Ltd
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version, along with the "Special Exception" for use of
# the program along with SSL, set forth below. This program is distributed
# in the hope that it will be useful, but WITHOUT ANY WARRANTY;
# without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details. You should have received a copy of the GNU General Public
# License along with this program.  If not, see
# <http://www.gnu.org/licenses/>.
#
# The author can be reached by email at clearwater@metaswitch.com or by
# post at Metaswitch Networks Ltd, 100 Church St, Enfield EN2 6BQ, UK
#
# Special Exception
# Metaswitch Networks Ltd  grants you permission to copy, modify,
# propagate, and distribute a work formed by combining OpenSSL with The
# Software, or a work derivative of such a combination, even if such
# copying, modification, propagation, or distribution would otherwise
# violate the terms of the GPL. You must comply with the GPL in all
# respects for all of the code used other than OpenSSL.
# "OpenSSL" means OpenSSL toolkit software distributed by the OpenSSL
# Project and licensed under the OpenSSL Licenses, or a work based on such
# software and licensed under the OpenSSL Licenses.
# "OpenSSL Licenses" means the OpenSSL License and Original SSLeay License
# under which the OpenSSL Project distributes the OpenSSL toolkit software,
# as those licenses appear in the file LICENSE-OPENSSL.


# This module provides a method for transporting alarm requests to a net-
# snmp alarm sub-agent for further handling. If the agent is unavailable,
# the request will timeout after 2 seconds and be dropped.


import logging
from threading import Thread, Condition
from .constants import RAISE_TOO_LONG_CLUSTERING, CLEAR_TOO_LONG_CLUSTERING
import imp

_log = logging.getLogger("metaswitch.clearwater.cluster_manager.alarms")

sendrequest = None

try:
    file, pathname, description = imp.find_module("alarms", ["/usr/share/clearwater/bin"])
    mod = imp.load_module("alarms", file, pathname, description)
    sendrequest = mod.sendrequest
except ImportError:
    _log.error("Could not import /usr/share/clearwater/bin/alarms.py, alarms will not be sent")


def issue_alarm(identifier):
    if sendrequest:
        sendrequest(["issue-alarm", "cluster-manager", identifier])


class TooLongAlarm(object):
    def __init__(self, delay=(15*60)):
        self._condvar = Condition()
        self._timer_thread = None
        self._should_alarm = False
        self._delay = delay

    def alarm(self):
        self._condvar.acquire()
        self._condvar.wait(self._delay)
        if self._should_alarm:
            issue_alarm(RAISE_TOO_LONG_CLUSTERING)
        self._condvar.release()

    def trigger(self, thread_name="Alarm thread"):
        self._should_alarm = True
        if self._timer_thread is None:
            self._timer_thread = Thread(target=self.alarm, name=thread_name)
            self._timer_thread.start()

    def quit(self):
        if self._timer_thread is not None:
            self._should_alarm = False
            self._condvar.acquire()
            self._condvar.notify()
            self._condvar.release()
            self._timer_thread.join()

    def cancel(self):
        self._condvar.acquire()
        self._should_alarm = False

        # cancel the thread
        self._condvar.notify()
        self._timer_thread = None

        # clear the alarm
        issue_alarm(CLEAR_TOO_LONG_CLUSTERING)
        self._condvar.release()