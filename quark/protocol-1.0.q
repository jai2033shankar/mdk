quark 1.0;

package datawire_mdk_protocol 2.0.14;

import quark.concurrent;
import quark.reflect;

include mdk_runtime.q;

import mdk_runtime;
import mdk_runtime.actors;

namespace mdk_protocol {

    @doc("Returns whether a list contains a given value.")
    bool contains(List<String> values, String value) {
        int idx = 0;
        while (idx < values.size()) {
            if (value == values[idx]) {
                return true;
            }
            idx = idx + 1;
        }
        return false;
    }

    @doc("""JSON serializable object.

    If it has have a String field called _json_type, that will be set as the
    'type' field in serialized JSON.
    """)
    class Serializable {
        @doc("Decode JSON into a particular class. XXX TURN INTO FUNCTION")
        static Serializable decodeClassName(String name, String encoded) {
            JSONObject json = encoded.parseJSON();
            Class clazz = Class.get(name);
            Serializable obj = ?clazz.construct([]);
            if (obj == null) {
                panic("could not construct " + clazz.getName() + " from this json: " + encoded);
            }
            fromJSON(clazz, obj, json);
            return obj;
        }

        String encode() {
            Class clazz = self.getClass();
            JSONObject json = toJSON(self, clazz);
            String jsonType = ?self.getField("_json_type");
            if (jsonType != null) {
                json["type"] = jsonType;
            }
            String encoded = json.toString();
            return encoded;
        }
    }

    @doc("""
        A Lamport Clock is a logical structure meant to allow partial causal ordering. Ours is a list of
        integers such that adding an integer implies adding a new level to the causality tree.

        Within a level, time is indicated by incrementing the clock, so

        [1,2,3] comes before [1,2,4] which comes before [1,2,5]

        Adding an element to the clock implies causality, so [1,2,4,1-N] is _by definition_ a sequence that was
        _caused by_ the sequence of [1,2,1-3].

        Note that LamportClock is lowish-level support. SharedContext puts some more structure around this, too.
    """)
    class LamportClock extends Serializable {
        // XXX Serialization breaks at the moment if this isn't a private element.
        Lock _mutex = new Lock();
        List<int> clocks = [];

        // XXX this could work a lot nicer with a parameterized method
        // in Serialize and a static class reference
        static LamportClock decode(String encoded) {
            return ?Serializable.decodeClassName("mdk_protocol.LamportClock", encoded);
        }

        @doc("""
            Return a neatly-formatted list of all of our clock elements (e.g. 1,2,4,1) for use as a name or
            a key.
        """)
        String key() {
            _mutex.acquire();

            List<String> tmp = [];

            int i = 0;

            while (i < self.clocks.size()) {
                tmp.add(self.clocks[i].toString());
                i = i + 1;
            }

            String str = ",".join(tmp);

            _mutex.release();

            return str;
        }

        // XXX Not automagically mapped to str() or the like, even though
        // something should be.
        String toString() {
            _mutex.acquire();

            String str = "<LamportClock " + self.key() + ">";

            _mutex.release();

            return str;
        }

        @doc("""
            Enter a new level of causality. Returns the value to pass to later pass to leave to get back to the
            current level of causality.
        """)
        int enter() {
            _mutex.acquire();

            int current = -1;

            self.clocks.add(0);
            current = self.clocks.size();

            _mutex.release();

            return current;
        }

        @doc("""
            Leave deeper levels of causality. popTo should be the value returned when you enter()d this level.
        """)
        int leave(int popTo) {
            _mutex.acquire();

            int current = -1;

            self.clocks = self.clocks.slice(0, popTo);
            current = self.clocks.size();

            _mutex.release();

            return current;
        }

        @doc("""
            Increment the clock for our current level of causality (which is always the last element in the list).
            If there are no elements in our clock, do nothing.
        """)
        void tick() {
            _mutex.acquire();

            int current = self.clocks.size();

            if (current > 0) {
                self.clocks[current - 1] = self.clocks[current - 1] + 1;
            }

            _mutex.release();
        }
    }

    class SharedContext extends Serializable {
        @doc("""
             Every SharedContext is given an ID at the moment of its
             creation; this is its traceId. Every operation started
             as a result of the thing that caused the SharedContext to
             be created must use the same SharedContext, and its
             traceId will _never_ _change_.
        """)
        String traceId = Context.runtime().uuid();

        @doc("""
            To track causality, we use a Lamport clock.
        """)
        LamportClock clock = new LamportClock();

        @doc("""
             We also provide a map of properties for later extension. Rememeber
             that these, too, will be shared across the whole system.
        """)
        Map<String, Object> properties = {};

        int _lastEntry = 0;

        SharedContext() {
            self._lastEntry = self.clock.enter();
        }

        @doc("""Set the traceId for this SharedContext.""")
        SharedContext withTraceId(String traceId) {
            self.traceId = traceId;
            return self;
        }

        // XXX this could work a lot nicer with a parameterized method
        // in Serialize and a static class reference
        static SharedContext decode(String encoded) {
            return ?Serializable.decodeClassName("mdk_protocol.SharedContext", encoded);
        }

        String clockStr(String pfx) {
            String cs = "";

            if (self.clock != null) {
                cs = pfx + self.clock.key();
            }

            return cs;
        }

        String key() {
            return self.traceId + self.clockStr(":");
        }

        // XXX Not automagically mapped to str() or the like, even though
        // something should be.
        String toString() {
            return "<SCTX t:" + self.traceId + self.clockStr(" c:") + ">";
        }

        @doc("""
            Tick the clock at our current causality level.
        """)
        void tick() {
            self.clock.tick();
        }

        @doc("""
            Return a SharedContext one level deeper in causality.

            NOTE WELL: THIS RETURNS A NEW SharedContext RATHER THAN MODIFYING THIS ONE. It is NOT SUPPORTED
            to modify the causality level of a SharedContext in place.
        """)
        SharedContext start_span() {
            // Tick first.
            self.tick();

            // Duplicate this object...
            SharedContext newContext = SharedContext.decode(self.encode());

            // ...open a new span...
            newContext._lastEntry = newContext.clock.enter();

            // ...and return the new context.
            return newContext;
        }

        @doc("""
            Return a SharedContext one level higher in causality. In practice, most callers should probably stop
            using this context, and the new one, after calling this method.

            NOTE WELL: THIS RETURNS A NEW SharedContext RATHER THAN MODIFYING THIS ONE. It is NOT SUPPORTED
            to modify the causality level of a SharedContext in place.
        """)
        SharedContext finish_span() {
            // Duplicate this object...
            SharedContext newContext = SharedContext.decode(self.encode());

            // ...leave...
            newContext._lastEntry = newContext.clock.leave(newContext._lastEntry);

            // ...and return the new context.
            return newContext;
        }

        @doc("Return a copy of a SharedContext.")
        SharedContext copy() {
            return SharedContext.decode(self.encode());
        }
    }

    @doc("A message sent whenever a new connection is opened, by both sides.")
    class Open extends Serializable {
        static String _json_type = "open";

        String version = "2.0.0";
        Map<String,String> properties = {};
    }

    // XXX: this should probably go somewhere in the library
    @doc("A value class for sending error informationto a remote peer.")
    class ProtocolError {
        @doc("Symbolic error code, alphanumerics and underscores only.")
        String code;

        @doc("Human readable short description.")
        String title;

        @doc("A detailed description.")
        String detail;

        @doc("A unique identifier for this particular occurrence of the problem.")
        String id;
    }

    @doc("Close the event stream.")
    class Close extends Serializable {
        static String _json_type = "close";

        ProtocolError error;
    }

    @doc("Sent to a subscriber every once in a while, to tell subscribers they can send data.")
    class Pump {}

    @doc("Sent to a subscriber when connection happens.")
    class WSConnected {
        Actor websock;

        WSConnected(Actor websock) {
            self.websock = websock;
        }
    }

    @doc("Higher-level interface for subscribers, to be utilized with _subscriberDispatch.")
    interface WSClientSubscriber extends Actor {
        @doc("Handle an incoming JSON message received from the server.")
        void onMessageFromServer(JSONObject message);

        @doc("Called with WebSocket actor when the WSClient connects to the server.")
        void onWSConnected(Actor websocket);

        @doc("Called when the WSClient notifies the subscriber it can send data.")
        void onPump();
    }

    @doc("""Dispatch actor messages to a WSClientSubscriber.

    Call this in onMessage to handle WSMessage, WSConnected and Pump messages
    from the WSClient.
    """)
    void _subscriberDispatch(WSClientSubscriber subscriber, Object message) {
        String klass = message.getClass().id;
        // WSClient has connected to the server:
        if (klass == "mdk_protocol.WSConnected") {
            WSConnected connected = ?message;
            subscriber.onWSConnected(connected.websock);
            return;
        }
        // The WSClient is telling us we can send periodic messages:
        if (klass == "mdk_protocol.Pump") {

            subscriber.onPump();
            return;
        }
        // The WSClient has received a message:
        if (klass == "mdk_runtime.WSMessage") {
            WSMessage wsmessage = ?message;
            JSONObject json = wsmessage.body.parseJSON();
            subscriber.onMessageFromServer(json);
            return;
        }
    }

    @doc("Handle Open and Close messages.")
    class OpenCloseSubscriber extends WSClientSubscriber {
        MessageDispatcher _dispatcher;
        WSClient _wsclient;

        OpenCloseSubscriber(WSClient client) {
            self._wsclient = client;
            self._wsclient.subscribe(self);
        }

        // Actor implementation
        void onStart(MessageDispatcher dispatcher) {
            self._dispatcher = dispatcher;
        }

        void onMessage(Actor origin, Object message) {
            _subscriberDispatch(self, message);
        }

        void onStop() {}

        // WSClientSubscriber implementation
        void onMessageFromServer(JSONObject message) {
            String type = message["type"];
            if (contains(["open", "mdk.protocol.Open", "discovery.protocol.Open"],
                         type)) {
                self.onOpen();
                return;
            }
            if (contains(["close", "mdk.protocol.Close", "discovery.protocol.Close"],
                         type)) {
                Close close = new Close();
                fromJSON(close.getClass(), close, message);
                self.onClose(close);
                return;
            }
        }

        void onWSConnected(Actor websocket) {
            // Send Open message to the server:
            self._dispatcher.tell(self, new Open().encode(), websocket);
        }

        void onPump() {}

        // WebSocket message handlers:
        void onOpen() {
            // Should assert version here ...
        }

        void onClose(Close close) {
            self._wsclient.onClose(close.error != null);
        }

    }

    @doc("Common protocol machinery for web socket based protocol clients.")
    class WSClient extends Actor {
        Logger logger = new Logger("protocol");

        float firstDelay = 1.0;
        float maxDelay = 16.0;
        float reconnectDelay = firstDelay;
        float ttl = 30.0;
        float tick = 1.0;

        WSActor sock = null;

        long lastConnectAttempt = 0L;

        Time timeService;
        Actor schedulingActor;
        WebSockets websockets;
        MessageDispatcher dispatcher;

        // URL to connect to
        String url;
        // Token to send for authentication
        String token;
        // Actors subscribed to Pump and passed on WSMessage messages:
        List<Actor> subscribers = [];
        // True if we are started:
        bool _started = false;

        WSClient(MDKRuntime runtime, String url, String token) {
            self.dispatcher = runtime.dispatcher;
            self.timeService = runtime.getTimeService();
            self.schedulingActor = runtime.getScheduleService();
            self.websockets = runtime.getWebSocketsService();
            self.url = url;
            self.token = token;
        }

        @doc("""Subscribe to messages from the server.

        Do this before starting the WSClient.

        The given Actor subscribes to WSConnected, all WSMessage received by the
        WSClient, as well as a periodic Pump message.
        """)
        void subscribe(Actor subscriber) {
            self.subscribers.add(subscriber);
        }

        bool isStarted() {
            return _started;
        }

        bool isConnected() {
            return sock != null;
        }

        void schedule(float time) {
            self.dispatcher.tell(self, new Schedule("wakeup", time), self.schedulingActor);
        }

        void scheduleReconnect() {
            schedule(reconnectDelay);
        }

        @doc("Called when the connection is closed via message by the server.")
        void onClose(bool error) {
            logger.info("close!");
            if (error) {
                doBackoff();
            } else {
                reconnectDelay = firstDelay;
            }
        }

        void doBackoff() {
            reconnectDelay = 2.0*reconnectDelay;

            if (reconnectDelay > maxDelay) {
                reconnectDelay = maxDelay;
            }
            logger.info("backing off, reconnecting in " + reconnectDelay.toString() + " seconds");
        }

        // Actor interface:
        void onStart(MessageDispatcher dispatcher) {
            self._started = true;
            schedule(0.0);
        }

        void onStop() {
            self._started = false;
            if (isConnected()) {
                self.dispatcher.tell(self, new WSClose(), sock);
                sock = null;
            }
        }

        void onMessage(Actor origin, Object message) {
            String typeId = message.getClass().id;
            if (typeId == "mdk_runtime.Happening") {
                self.onScheduledEvent();
                return;
            }
            if (typeId == "mdk_runtime.WSClosed") {
                self.onWSClosed();
                return;
            }
            if (typeId == "mdk_runtime.WSMessage") {
                // Send WSMessage on to subscribers; one of them will handle it:
                int idx = 0;
                while (idx < self.subscribers.size()) {
                    self.dispatcher.tell(self, message, self.subscribers[idx]);
                    idx = idx + 1;
                }
                return;
            }
        }

        void onScheduledEvent() {
            /*
              Do our periodic chores here, this will involve checking
              the desired state held by disco against our actual
              state and taking any measures necessary to address the
              difference:


              - isStarted() holds the desired connectedness
              state. The isConnected() accessor holds the actual
              connectedness state. If these differ then do what is
              necessry to make the desired state actual.

              - If we haven't sent a heartbeat recently enough, then
              do that.
            */
            long rightNow = (self.timeService.time()*1000.0).round();
            long reconnectInterval = (reconnectDelay*1000.0).round();

            if (isConnected()) {
                if (isStarted()) {
                    pump();
                }
            } else {
                if (isStarted() && (rightNow - lastConnectAttempt) >= reconnectInterval) {
                    doOpen();
                }
            }

            if (isStarted()) {
                schedule(tick);
            }
        }

        void doOpen() {
            lastConnectAttempt = (self.timeService.time()*1000.0).round();
            String sockUrl = url;
            if (token != null) {
                sockUrl = sockUrl + "?token=" + token;
            }

            logger.info("opening " + url);

            self.websockets.connect(sockUrl, self)
                .andEither(bind(self, "onWSConnected", []),
                           bind(self, "onWSError", []));
        }

        void startup() {
            WSConnected message = new WSConnected(self.sock);
            int idx = 0;
            while (idx < subscribers.size()) {
                self.dispatcher.tell(self, message, subscribers[idx]);
                idx = idx + 1;
            }
        }

        void pump() {
            Pump message = new Pump();
            int idx = 0;
            while (idx < subscribers.size()) {
                self.dispatcher.tell(self, message, subscribers[idx]);
                idx = idx + 1;
            }
        }

        void onWSConnected(WSActor socket) {
            // Whenever we (re)connect, notify the server of any
            // nodes we have registered.
            logger.info("connected to " + url + " via " + socket.toString());

            reconnectDelay = firstDelay;
            sock = socket;

            startup();
            pump();
        }

        void onWSError(Error error) {
            logger.error("onWSError in protocol! " + error.toString());
            // Any non-transient errors should be reported back to the
            // user via any Nodes they have requested.
            doBackoff();
        }

        void onWSClosed() {
            logger.info("closed " + url);
            sock = null;
        }
    }

}
