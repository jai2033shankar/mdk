"""
Tests for the MDK public API that are easier to do in Python.
"""
from time import time
from builtins import range
from past.builtins import unicode

from unittest import TestCase
from tempfile import mkdtemp
from collections import Counter

import hypothesis.strategies as st
from hypothesis import given, assume

from mdk import MDKImpl
from mdk_runtime import fakeRuntime
from mdk_discovery import (
    ReplaceCluster, NodeActive, RecordingFailurePolicyFactory,
)

from .test_discovery import create_node


class MDKInitializationTestCase(TestCase):
    """
    Tests for top-level MDK API startup.
    """
    def test_no_datawire_token(self):
        """
        If DATAWIRE_TOKEN is not set neither the TracingClient nor the DiscoClient
        are started.
        """
        # Disable connecting to our Discovery server:
        runtime = fakeRuntime()
        runtime.getEnvVarsService().set("MDK_DISCOVERY_SOURCE", "synapse:path=" + mkdtemp())

        # Start the MDK:
        mdk = MDKImpl(runtime)
        mdk.start()

        # Do a bunch of logging:
        session = mdk.session()
        session.info("category", "hello!")
        session.error("category", "ono")
        session.warn("category", "gazoots")
        session.critical("category", "aaaaaaa")
        session.debug("category", "behold!")

        # Time passes...
        scheduleService = runtime.getScheduleService()
        for i in range(10):
            scheduleService.advance(1.0)
            scheduleService.pump()

        # No WebSocket connections made:
        self.assertFalse(runtime.getWebSocketsService().fakeActors)


def add_bools(list_of_lists):
    """
    Given recursive list that can contain other lists, return tuple of that plus
    a booleans strategy for each list.
    """
    l = []
    def count(recursive):
        l.append(1)
        for child in recursive:
            if isinstance(child, list):
                count(child)
    count(list_of_lists)
    return st.tuples(st.just(list_of_lists), st.tuples(*[st.sampled_from([True, False]) for i in l]))


class InteractionTestCase(TestCase):
    """Tests for the Session interaction API."""

    def init(self):
        """Initialize an empty environment."""
        # Initialize runtime and MDK:
        self.runtime = fakeRuntime()
        self.runtime.getEnvVarsService().set("DATAWIRE_TOKEN", "somevalue")
        self.runtime.dependencies.registerService("failurepolicy_factory",
                                                  RecordingFailurePolicyFactory())
        self.mdk = MDKImpl(self.runtime)
        self.mdk.start()
        self.disco = self.mdk._disco
        # Create a session:
        self.session = self.mdk.session()

    def setUp(self):
        self.init()

        # Register some nodes:
        self.node1 = create_node("a1", "service1")
        self.node2 = create_node("a2", "service1")
        self.node3 = create_node("b1", "service2")
        self.node4 = create_node("b2", "service2")
        self.all_nodes = set([self.node1, self.node2, self.node3, self.node4])

        self.disco.onMessage(None, ReplaceCluster("service1",
                                                  [self.node1, self.node2]))
        self.disco.onMessage(None, ReplaceCluster("service2",
                                                  [self.node3, self.node4]))

    def assertPolicyState(self, policies, successes, failures):
        """
        Assert that the given FailurePolicy instances has the given number of
        success() and failure() calls.
        """
        for policy in policies:
            self.assertEqual((policy.successes, policy.failures),
                             (successes, failures))

    def test_successfulInteraction(self):
        """
        All nodes resolved within a successful interaction are marked as
        succeeding to connect.
        """
        self.session.start_interaction()
        node = self.session.resolve("service1", "1.0")
        another_node = self.session.resolve("service2", "1.0")
        self.session.finish_interaction()
        expected_successful = [self.disco.failurePolicy(node),
                               self.disco.failurePolicy(another_node)]
        expected_nothing = list(self.disco.failurePolicy(n) for n in
                                self.all_nodes if
                                n.address not in [node.address, another_node.address])
        self.assertPolicyState(expected_successful, 1, 0)
        self.assertPolicyState(expected_nothing, 0, 0)

    def test_failedInteraction(self):
        """All nodes resolved with a failing interaction are marked as failures."""
        self.session.start_interaction()
        node = self.session.resolve("service1", "1.0")
        another_node = self.session.resolve("service2", "1.0")
        self.session.fail_interaction("OHNO")
        self.session.finish_interaction()
        expected_failed = [self.disco.failurePolicy(node),
                           self.disco.failurePolicy(another_node)]
        expected_nothing = list(self.disco.failurePolicy(n) for n in
                                self.all_nodes if
                                n.address not in [node.address, another_node.address])
        self.assertPolicyState(expected_failed, 0, 1)
        self.assertPolicyState(expected_nothing, 0, 0)

    def test_failedResetsInteraction(self):
        """
        Nodes resolved after a failing interaction are not marked as failed when
        finish is called.
        """
        self.session.start_interaction()
        node = self.session.resolve("service1", "1.0")
        self.session.fail_interaction("OHNO")
        another_node = self.session.resolve("service2", "1.0")
        self.session.finish_interaction()
        expected_failed = [self.disco.failurePolicy(node)]
        expected_succeeded = [self.disco.failurePolicy(another_node)]
        expected_nothing = list(self.disco.failurePolicy(n) for n in
                                self.all_nodes if
                                n.address not in [node.address, another_node.address])
        self.assertPolicyState(expected_failed, 0, 1)
        self.assertPolicyState(expected_succeeded, 1, 0)
        self.assertPolicyState(expected_nothing, 0, 0)

    def test_finishedResetsInteraction(self):
        """
        Each new interaction allows marking Nodes with new information.
        """
        self.session.start_interaction()
        node = self.session.resolve("service1", "1.0")
        self.session.fail_interaction("OHNO")
        self.session.finish_interaction()

        self.session.start_interaction()
        # Resolve same node again:
        while True:
            another_node = self.session.resolve("service1", "1.0")
            if node.address == another_node.address:
                break
        self.session.finish_interaction()

        self.assertPolicyState([self.disco.failurePolicy(node)], 1, 1)

    @given(st.recursive(st.text(alphabet="abcd", min_size=1, max_size=3),
                        st.lists).flatmap(add_bools))
    def test_nestedInteractions(self, values):
        """
        Nested interactions operate independently of parent interactions.

        :param values: a two-tuple composed of:
           - a recursive list of unicode and other recursive lists - list start
             means begin interaction, string means node resolve, list end means
             finish interaction.
           - list of False/True; True means failed interaction
        """
        requested_interactions, failures = values
        failures = iter(failures)
        assume(not isinstance(requested_interactions, unicode))
        self.init()

        failures = iter(failures)
        created_services = {}
        expected_success_nodes = Counter()
        expected_failed_nodes = Counter()

        def run_interaction(children):
            fails = next(failures)
            self.session.start_interaction()
            for child in children:
                if isinstance(child, unicode):
                    # Make sure disco knows about the node:
                    if child in created_services:
                        node = created_services[child]
                    else:
                        node = create_node(child, child)
                        created_services[child] = node
                    self.disco.onMessage(None, NodeActive(node))
                    # Make sure the child Node is resolved in the interaction
                    self.session.resolve(node.service, "1.0")
                    if fails:
                        expected_failed_nodes[node] += 1
                    else:
                        expected_success_nodes[node] += 1
                else:
                    run_interaction(child)
            if fails:
                self.session.fail_interaction("OHNO")
            self.session.finish_interaction()

        run_interaction(requested_interactions)
        for node in set(expected_failed_nodes) | set(expected_success_nodes):
            policy = self.disco.failurePolicy(node)
            self.assertEqual((policy.successes, policy.failures),
                             (expected_success_nodes[node],
                              expected_failed_nodes[node]))


class SessionDeadlineTests(TestCase):
    """Tests for the session deadline."""

    def setUp(self):
        """Initialize an empty environment."""
        # Initialize runtime and MDK:
        self.runtime = fakeRuntime()
        self.runtime.getEnvVarsService().set("DATAWIRE_TOKEN", "something")
        self.mdk = MDKImpl(self.runtime)
        self.mdk.start()
        self.session = self.mdk.session()

    def test_setDeadline(self):
        """A set deadline can be retrieved."""
        self.session.setDeadline(13.5)
        self.assertEqual(13.5, self.session.getRemainingTime())

    def test_notSetDeadline(self):
        """Deadline is null if not set."""
        self.assertEqual(None, self.session.getRemainingTime())

    def test_deadlineChangesAsTimePasses(self):
        """If time passes the deadline goes down."""
        self.session.setDeadline(13.5)
        self.runtime.getTimeService().advance(2.0)
        self.assertEqual(11.5, self.session.getRemainingTime())

    def test_setDeadlineTwice(self):
        """Deadlines can be decreased by setting, but not increased."""
        self.session.setDeadline(10.0)
        self.session.setDeadline(9.0)
        decreased = self.session.getRemainingTime()
        self.session.setDeadline(11.0)
        still_decreased = self.session.getRemainingTime()
        self.assertEqual((decreased, still_decreased), (9.0, 9.0))

    def test_serialization(self):
        """A serialized session preserves the deadline."""
        self.session.setDeadline(10.0)
        self.session.set("xx", "yy")
        serialized = self.session.externalize()
        session2 = self.mdk.join(serialized)
        self.assertEqual(session2.getRemainingTime(), 10.0)

    def test_mdkDefault(self):
        """The MDK can set a default deadline for new sessions."""
        self.mdk.setDefaultDeadline(5.0)
        session = self.mdk.session()
        self.assertEqual(session.getRemainingTime(), 5.0)

    def test_mdkDefaultForJoinedSessions(self):
        """
        Deadlines for joined sessions are decreased to the MDK default deadline, but
        never increased.
        """
        session1 = self.mdk.session()
        session1.setDeadline(1.0)
        encoded1 = session1.externalize()

        session2 = self.mdk.session()
        session2.setDeadline(3.0)
        encoded2 = session2.externalize()

        self.mdk.setDefaultDeadline(2.0)
        self.assertEqual((1.0, 2.0),
                         (self.mdk.join(encoded1).getRemainingTime(),
                          self.mdk.join(encoded2).getRemainingTime()))

    def test_resolveNoDeadline(self):
        """
        If a deadline higher than 10 seconds was set, resolving still times out after
        10.0 seconds.
        """
        self.session.setDeadline(20.0)
        start = time()
        with self.assertRaises(Exception):
            self.session.resolve("unknown", "1.0")
        self.assertAlmostEqual(time() - start, 10.0, delta=1)

    def test_resolveLowerDeadline(self):
        """
        If a deadline lower than 10 seconds was set, resolving happens after the
        lower deadline.
        """
        self.session.setDeadline(3.0)
        start = time()
        with self.assertRaises(Exception):
            self.session.resolve("unknown", "1.0")
        self.assertAlmostEqual(time() - start, 3.0, delta=1)
