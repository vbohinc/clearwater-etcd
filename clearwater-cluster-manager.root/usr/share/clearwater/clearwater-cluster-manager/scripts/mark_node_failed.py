# Copyright (C) Metaswitch Networks 2015
# If license terms are provided to you in a COPYING file in the root directory
# of the source code repository by which you are accessing this code, then
# the license outlined in that COPYING file applies to your use.
# Otherwise no rights are granted except for those provided to you by
# Metaswitch Networks in a separate written agreement.

"""mark_node_failed

Usage:
  mark_node_failed.py <local_ip> <site> <node_type> <datastore> <dead_node_ip> <etcd_key> [--foreground] [--cassandra-container-id <CONTAINER_ID>]
"""

from docopt import docopt
from os import sys
import consul
import json
import logging
import time
from metaswitch.clearwater.cluster_manager.consul_synchronizer import \
    ConsulSynchronizer
from metaswitch.clearwater.cluster_manager.null_plugin import \
    NullPlugin


def make_key(site, node_type, datastore, etcd_key):
    if datastore == "cassandra":
        return "{}/{}/clustering/{}".format(etcd_key, node_type, datastore)
    else:
        return "/{}/{}/{}/clustering/{}".format(etcd_key,
                                                site,
                                                node_type,
                                                datastore)


def get_from_kv(kv, key, retry=10):
    """Get a value from the Consul datastore. Produces a dict - e.g.
    {"172.16.0.117": "normal", "172.16.0.145": "normal"}
    """
    try:
        (_index, value) = kv.get(key)
    except consul.ConsulException as e:
        # If the node with the Consul leader is the one that failed, the Consul
        # cluster may take several seconds to notice this and elect a new
        # leader.  Before a new leader is elected, Consul will throw
        # `ConsulException: 500 No cluster leader`. Thus, on a
        # `ConsulException` we wait a few seconds and try again. If the problem
        # was one of cluster leadership, that should give it enough time to
        # elect a new leader. If the second call fails, there's probably
        # something wrong with the Consul cluster that will require manual
        # intervention to sort out.
        logging.warning("Failed to read from Consul, waiting to retry: {}"
                        .format(e))
        time.sleep(retry)
        (_index, value) = kv.get(key)

    raw_value = value["Value"]

    # Values are stored as a JSON dict
    return json.loads(raw_value)


arguments = docopt(__doc__)

local_ip = arguments["<local_ip>"]
site = arguments["<site>"]
node_type = arguments["<node_type>"]
datastore = arguments["<datastore>"]
dead_node_ip = arguments["<dead_node_ip>"]
etcd_key = arguments["<etcd_key>"]
foreground = arguments["--foreground"]
cassandra_id = arguments["<CONTAINER_ID>"]

if foreground:
    # In foreground mode, write logs to stdout
    logging.basicConfig(
        stream=sys.stdout,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.DEBUG)
else:
    logfile = "/var/log/clearwater-etcd/mark_node_failed.log"
    print "Detailed output being sent to %s" % logfile
    logging.basicConfig(
        filename=logfile,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.DEBUG)

key = make_key(site, node_type, datastore, etcd_key)
logging.info("Using etcd key %s" % (key))

c = consul.Consul(host=local_ip).kv
state = get_from_kv(c, key, retry=60)

if dead_node_ip not in state:
    print "%s not in cluster - no work required" % dead_node_ip
    sys.exit(0)

if datastore == "cassandra":
    try:
        sys.path.append(
            "/usr/share/clearwater/clearwater-cluster-manager/failed_plugins")
        from ddd_failed_plugin import DddFailedPlugin
        plugin = DddFailedPlugin(key,
                                 dead_node_ip,
                                 cassandra_container_id=cassandra_id)

        error_syncer = ConsulSynchronizer(plugin,
                                          dead_node_ip,
                                          db_ip=local_ip,
                                          force_leave=True)
    except ImportError:
        logging.error("You must run mark_node_failed on a node that has "
                      "Cassandra installed to remove a node from a Cassandra "
                      "cluster")
        sys.exit(1)
else:
    error_syncer = ConsulSynchronizer(NullPlugin(key),
                                      dead_node_ip,
                                      db_ip=local_ip,
                                      force_leave=True)

logging.info("Marking node as failed and removing it from the cluster - will "
             "take at least 30 seconds")
# Move the dead node into ERROR state to allow in-progress operations to
# complete
error_syncer.mark_node_failed()

# Move the dead node out of the cluster
error_syncer.start_thread()
error_syncer.leave_cluster()

# Wait for it to leave
error_syncer.thread.join()

logging.info(
    "{} has left the Cassandra cluster - waiting for removal from Consul"
    .format(dead_node_ip))

for i in range(0, 100):
    new_value = get_from_kv(c, key).get(dead_node_ip)

    if new_value is None:
        logging.info("Success: removed from Consul")
        sys.exit(0)
    elif new_value != "finished":
        logging.error("Unexpected state: {}".format(new_value))
        sys.exit(1)
    else:
        logging.debug("Waiting for finished node to be removed from Consul")
        time.sleep(6)

logging.error(
    "Timed out waiting for {} to be removed from Consul".format(dead_node_ip))
sys.exit(1)
