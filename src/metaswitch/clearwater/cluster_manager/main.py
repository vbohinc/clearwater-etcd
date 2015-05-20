#!/usr/bin/env python

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

"""Clearwater Cluster Manager

Usage:
  main.py --local-ip=IP --local-site=NAME --remote-site=NAME
          [--foreground] [--log-level=LVL] [--log-directory=DIR]
          [--pidfile=FILE]

Options:
  -h --help                   Show this screen.
  --local-ip=IP               IP address
  --local-site=NAME           Name of local site
  --remote-site=NAME          Name of remote site
  --foreground                Don't daemonise
  --log-level=LVL             Level to log at, 0-4 [default: 3]
  --log-directory=DIR         Directory to log to [default: ./]
  --pidfile=FILE              Pidfile to write [default: ./cluster-manager.pid]

"""

from docopt import docopt

from metaswitch.common import logging_config, utils
from metaswitch.clearwater.cluster_manager.plugin_loader \
    import load_plugins_in_dir
from metaswitch.clearwater.cluster_manager.etcd_synchronizer \
    import EtcdSynchronizer
import logging
import os
from threading import Thread
import signal

_log = logging.getLogger("metaswitch.clearwater.cluster_manager.main")

LOG_LEVELS = {'0': logging.CRITICAL,
              '1': logging.ERROR,
              '2': logging.WARNING,
              '3': logging.INFO,
              '4': logging.DEBUG}


def install_sigquit_handler(plugins):
    def sigquit_handler(sig, stack):
        _log.debug("Handling SIGQUIT")
        for plugin in plugins:
            _log.debug("{} leaving cluster".format(plugin))
            plugin.leave_cluster()
    signal.signal(signal.SIGQUIT, sigquit_handler)


def main(args):
    arguments = docopt(__doc__, argv=args)

    listen_ip = arguments['--local-ip']
    local_site_name = arguments['--local-site']
    remote_site_name = arguments['--remote-site']
    log_dir = arguments['--log-directory']
    log_level = LOG_LEVELS.get(arguments['--log-level'], logging.DEBUG)

    stdout_err_log = os.path.join(log_dir, "cluster-manager.output.log")

    if not arguments['--foreground']:
        utils.daemonize(stdout_err_log)

    logging_config.configure_logging(log_level, log_dir, "cluster-manager")

    # urllib3 logs a WARNING log whenever it recreates a connection, but our
    # etcd usage does this frequently (to allow watch timeouts), so deliberately
    # ignore this log
    urllib_logger = logging.getLogger('urllib3')
    urllib_logger.setLevel(logging.ERROR)

    utils.install_sigusr1_handler("cluster-manager")

    # Drop a pidfile.
    pid = os.getpid()
    with open(arguments['--pidfile'], "w") as pidfile:
        pidfile.write(str(pid) + "\n")

    plugins_dir = "/usr/share/clearwater/clearwater-cluster-manager/plugins/"
    plugins = load_plugins_in_dir(plugins_dir,
                                  listen_ip,
                                  local_site_name,
                                  remote_site_name)
    plugins.sort(key=lambda x: x.key())
    plugins_to_use = []
    files = []
    skip = False
    for plugin in plugins:
        for plugin_file in plugin.files():
            if plugin_file in files:
                _log.info("Skipping plugin {} because {} "
                          "is already managed by another plugin"
                          .format(plugin, plugin_file))
                skip = True

        if not skip:
            plugins_to_use.append(plugin)
            files.extend(plugin.files())

    synchronizers = []
    threads = []
    for plugin in plugins_to_use:
        syncer = EtcdSynchronizer(plugin, listen_ip)
        thread = Thread(target=syncer.main)
        thread.daemon = True
        thread.start()

        synchronizers.append(syncer)
        threads.append(thread)
        _log.info("Loaded plugin %s" % plugin)

    install_sigquit_handler(synchronizers)

    for thread in threads:
        while thread.isAlive():
            thread.join(1)

if __name__ == '__main__':
    import sys
    main(sys.argv[1:])