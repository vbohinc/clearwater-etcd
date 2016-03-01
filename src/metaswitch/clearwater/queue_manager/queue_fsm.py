# Project Clearwater - IMS in the Cloud
# Copyright (C) 2015 Metaswitch Networks Ltd
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

import constants
from queue_config import QueueConfig
from alarms import QueueAlarm
from timers import QueueTimer
import logging

_log = logging.getLogger("queue_manager.queue_fsm")

class QueueFSM(object):

    def __init__(self, plugin, node_id, callback_func):
        self._queue_config = None

        self._plugin = plugin
        self._id = node_id
        self._running = True

        self._timer_callback_func = callback_func
        self._timer = None
        self._local_alarm = QueueAlarm(*self._plugin.local_alarm())
        self._global_alarm = QueueAlarm(*self._plugin.global_alarm())

        self._last_local_state = None

        # List of functions when in each local state. All the functions get
        # called, even if they change the local state
        self._local_fsm = {constants.LS_NO_QUEUE: [self._local_alarm.clear],
                           constants.LS_NO_QUEUE_ERROR: [self._local_alarm.critical],
                           constants.LS_FIRST_IN_QUEUE: [self._local_alarm.minor,
                                                         self.move_to_processing],
                           constants.LS_PROCESSING: [self._plugin.at_front_of_queue,
                                                     self._set_timer_with_id],
                           constants.LS_WAITING_ON_OTHER_NODE: [self._local_alarm.clear,
                                                                self._set_timer_with_current_node_id],
                           constants.LS_WAITING_ON_OTHER_NODE_ERROR: [self._local_alarm.critical,
                                                                      self._set_timer_with_current_node_id]}

        # List of functions when in each global state. These functions don't
        # change the state of the node/deployment
        self._global_actions = {constants.GS_NO_SYNC: [self._global_alarm.clear],
                                constants.GS_SYNC: [self._global_alarm.minor],
                                constants.GS_SYNC_ERROR: [self._global_alarm.critical],
                                constants.GS_NO_SYNC_ERROR: [self._global_alarm.critical]}

    def quit(self):
        if self._timer is not None:
            self._timer.clear()
        self._running = False

    def is_running(self):
        return self._running

    def move_to_processing(self):
        self._queue_config.move_to_processing()

    def fsm_update(self, queue_config):
        """Main state machine function.

        Arguments:
            - queue_config: The current value in etcd as a dictionary

        Returns: None (but the passed in queue_config is updated, which
                       the caller can decide whether to write back to etcd)
        """
        # Parse the current queue configuration
        self._queue_config = QueueConfig(self._id, queue_config)
        _log.debug("Node at the front of the queue is %s" % self._queue_config.node_at_the_front_of_the_queue())

        # Firstly, check if we've entered the FSM because a timer has popped.
        if self._timer is not None and self._timer.timer_popped:
            _log.info("Timer has popped %s" % self._timer.timer_id)

            # Does the timer relate to the node at the front of the queue?
            if self._timer.timer_id == self._queue_config.node_at_the_front_of_the_queue():
                # Is the node at the front of the queue this node?
                if self._queue_config.node_at_the_front_of_the_queue() == self._id:
                    self._local_alarm.critical()

                self._queue_config.mark_node_as_unresponsive(self._queue_config.node_at_the_front_of_the_queue())
                self._timer.clear()
                self._timer = None
                return
            else: #pragma: no cover
                self._timer.clear()
                self._timer = None

        # Now, check the local state and perform any appropriate actions
        local_queue_state = self._queue_config.calculate_local_state()
        _log.debug("Local state is {}".format(local_queue_state))

        if local_queue_state != self._last_local_state:
            for local_state_action in self._local_fsm[local_queue_state]:
                local_state_action()

        self._last_local_state = local_queue_state
        
        # Recalculate the global state, and raise the appropriate alarm given the
        # global state of the queue operation
        global_queue_state = self._queue_config.calculate_global_state()
        _log.debug("Global state is %s" % global_queue_state)
        for global_state_action in self._global_actions[global_queue_state]:
            global_state_action()

    def _set_timer_with_current_node_id(self):
        if self._timer != None: #pragma: no cover
            self._timer.clear()
        self._timer = QueueTimer(self._timer_callback_func)
        self._timer.set(self._queue_config.node_at_the_front_of_the_queue(), self._plugin.WAIT_FOR_OTHER_NODE)

    def _set_timer_with_id(self):
        if self._timer != None: #pragma: no cover
            self._timer.clear()
        self._timer = QueueTimer(self._timer_callback_func)
        self._timer.set(self._id, self._plugin.WAIT_FOR_THIS_NODE)