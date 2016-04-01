import logging
import selectors
import socket
import queue
from twisted.internet import protocol, reactor

log = logging.getLogger(__name__)

#concurrency_mode = 'twisted'
concurrency_mode = 'select'
#concurrency_mode = 'threads'


#class ConnectionManager():
    #def connect_peer(peer):
        #raise NotImplementedError

    #def start_event_loop():
        #raise NotImplementedError

    #def stop_event_loop():
        #raise NotImplementedError

# =============================================================================


class PeerConnectionProtocol(protocol.Protocol):
    def connectionMade(self):
        #log.debug('%s: connectionMade' % self.factory.peer)
        self.factory.peer.handle_connection_made(self)

    def dataReceived(self, data):
        #log.debug('%s: dataReceived' % self.factory.peer)
        self.factory.peer.handle_data_received(data)

    def connectionLost(self, reason):
        pass

    def write(self, data):
        self.transport.write(data)

    def disconnect(self):
        self.transport.loseConnection()


class PeerConnectionFactory(protocol.ClientFactory):
    protocol = PeerConnectionProtocol

    def __init__(self, peer):
        self.peer = peer

    def clientConnectionFailed(self, connector, reason):
        #log.warn('%s: clientConnectionFailed: %s' % (self.peer, reason))
        self.peer.handle_connection_failed()

    def clientConnectionLost(self, connector, reason):
        #log.warn('%s: clientConnectionLost: %s' % (self.peer, reason))
        self.peer.handle_connection_lost()


class ConnectionManagerTwisted():
    @staticmethod
    def connect_peer(peer):
        f = PeerConnectionFactory(peer)
        reactor.connectTCP(peer.ip, peer.port, f)

    @staticmethod
    def start_event_loop():
        reactor.run()

    @staticmethod
    def stop_event_loop():
        reactor.stop()

# =============================================================================


class ConnectionManagerSelect():
    def __init__(self):
        self.sel = selectors.DefaultSelector()
        self.conns = []
        self.loop_active = False

    def connect_peer(self, peer):
        try:
            conn = PeerConnectionSelect(self.sel, peer)
        except PeerConnectionFailed:
            return

        self.conns.append(conn)

    def start_event_loop(self):
        self.loop_active = True
        while self.loop_active:
            events = self.sel.select()
            for key, mask in events:
                callback = key.data
                callback(key.fileobj, mask)

    def stop_event_loop(self):
        for conn in self.conns:
            conn.disconnect()
        self.loop_active = False


class PeerConnectionSelect():
    def __init__(self, sel, peer):
        log.debug('PeerConnectionSelect.__init__: %s' % peer)
        self.sel = sel
        self.peer = peer
        self.write_queue = queue.Queue()
        self.connect()

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(2.0)
        try:
            self.sock.connect((self.peer.ip, self.peer.port))
        except OSError:
            self.handle_connection_failed()
            raise PeerConnectionFailed

        self.sock.setblocking(False)
        self.sel.register(
            self.sock, selectors.EVENT_READ, self.handle_event)
        self.peer.handle_connection_made(self)

    def handle_connection_failed(self):
        #log.debug('PeerConnectionSelect.handle_connection_failed')
        self.peer.handle_connection_failed()

    def handle_connection_lost(self):
        #log.debug('PeerConnectionSelect.handle_connection_lost')
        self.disconnect()
        self.peer.handle_connection_lost()

    def handle_event(self, sock, mask):
        assert(sock == self.sock)

        if mask & selectors.EVENT_WRITE:
            self.handle_event_write(mask)
        elif mask & selectors.EVENT_READ:
            self.handle_event_read(mask)
        else:
            raise Exception('Unexpected event mask: %s' % mask)

    def handle_event_read(self, mask):
        #log.debug('PeerConnectionSelect.handle_event_read')
        assert(mask == selectors.EVENT_READ)
        try:
            data = self.sock.recv(4096)
        except ConnectionError:
            self.handle_connection_lost()
            return

        if not data:
            self.handle_connection_lost()
            return

        self.peer.handle_data_received(data)

    def handle_event_write(self, mask):
        #log.debug('PeerConnectionSelect.handle_event_write')
        assert(mask == selectors.EVENT_WRITE)

        try:
            data = self.write_queue.get_nowait()
        except queue.Empty:
            # Disable write events.
            self.sel.modify(self.sock, selectors.EVENT_READ, self.handle_event)
            return

        try:
            self.sock.send(data)
        except BrokenPipeError:
            self.handle_connection_lost()
            return


    def write(self, data):
        #log.debug('PeerConnectionSelect.write: %s' % data)
        self.write_queue.put(data)
        # Enable write events.
        self.sel.modify(
            self.sock, selectors.EVENT_READ|selectors.EVENT_WRITE,
            self.handle_event)

    def disconnect(self):
        if self.sock:
            self.sel.unregister(self.sock)
            self.sock.close()
        self.sock = None


class PeerConnectionFailed(Exception):
    pass


# =============================================================================


class ConnectionManagerThreaded():
    def __init__(self):
        pass

    def connect_peer(self, peer):
        pass

    def start_event_loop(self):
        pass

    def stop_event_loop(self):
        pass

# =============================================================================

ConnectionManager = ConnectionManagerTwisted
if concurrency_mode == 'twisted':
    ConnectionManager = ConnectionManagerTwisted
elif concurrency_mode == 'select':
    ConnectionManager = ConnectionManagerSelect
elif concurrency_mode == 'threads':
    ConnectionManager = ConnectionManagerThreaded
