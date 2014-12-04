"""Blocking channels

Useful for test suites and blocking terminal interfaces.
"""

# Copyright (c) IPython Development Team.
# Distributed under the terms of the Modified BSD License.

try:
    from queue import Queue, Empty  # Py 3
except ImportError:
    from Queue import Queue, Empty  # Py 2

from IPython.kernel.channelsabc import ShellChannelABC, IOPubChannelABC, \
    StdInChannelABC
from IPython.kernel.channels import  HBChannel,\
    make_iopub_socket, make_shell_socket, make_stdin_socket,\
    InvalidPortNumber, major_protocol_version
from IPython.utils.py3compat import string_types, iteritems

# some utilities to validate message structure, these might get moved elsewhere
# if they prove to have more generic utility

def validate_string_list(lst):
    """Validate that the input is a list of strings.

    Raises ValueError if not."""
    if not isinstance(lst, list):
        raise ValueError('input %r must be a list' % lst)
    for x in lst:
        if not isinstance(x, string_types):
            raise ValueError('element %r in list must be a string' % x)


def validate_string_dict(dct):
    """Validate that the input is a dict with string keys and values.

    Raises ValueError if not."""
    for k,v in iteritems(dct):
        if not isinstance(k, string_types):
            raise ValueError('key %r in dict must be a string' % k)
        if not isinstance(v, string_types):
            raise ValueError('value %r in dict must be a string' % v)


class ZMQSocketChannel(object):
    """The base class for the channels that use ZMQ sockets."""
    context = None
    session = None
    socket = None
    ioloop = None
    stream = None
    _address = None
    _exiting = False
    proxy_methods = []

    def __init__(self, context, session, address):
        """Create a channel.

        Parameters
        ----------
        context : :class:`zmq.Context`
            The ZMQ context to use.
        session : :class:`session.Session`
            The session to use.
        address : zmq url
            Standard (ip, port) tuple that the kernel is listening on.
        """
        super(ZMQSocketChannel, self).__init__()
        self.daemon = True

        self.context = context
        self.session = session
        if isinstance(address, tuple):
            if address[1] == 0:
                message = 'The port number for a channel cannot be 0.'
                raise InvalidPortNumber(message)
            address = "tcp://%s:%i" % address
        self._address = address

    def _recv(self, **kwargs):
        msg = self.socket.recv_multipart(**kwargs)
        ident,smsg = self.session.feed_identities(msg)
        return self.session.deserialize(smsg)

    def get_msg(self, block=True, timeout=None):
        """ Gets a message if there is one that is ready. """
        if block:
            if timeout is not None:
                timeout *= 1000  # seconds to ms
            ready = self.socket.poll(timeout)
        else:
            ready = self.socket.poll(timeout=0)

        if ready:
            return self._recv()
        else:
            raise Empty

    def get_msgs(self):
        """ Get all messages that are currently ready. """
        msgs = []
        while True:
            try:
                msgs.append(self.get_msg(block=False))
            except Empty:
                break
        return msgs

    def msg_ready(self):
        """ Is there a message that has been received? """
        return bool(self.socket.poll(timeout=0))

    def close(self):
        if self.socket is not None:
            try:
                self.socket.close(linger=0)
            except Exception:
                pass
            self.socket = None
    stop =  close

    def is_alive(self):
        return (self.socket is not None)

    @property
    def address(self):
        """Get the channel's address as a zmq url string.

        These URLS have the form: 'tcp://127.0.0.1:5555'.
        """
        return self._address

    def _queue_send(self, msg):
        """Pass a message to the ZMQ socket to send
        """
        self.session.send(self.socket, msg)


class BlockingShellChannel(ZMQSocketChannel):
    """The shell channel for issuing request/replies to the kernel."""

    def start(self):
        self.socket = make_stdin_socket(self.context, self.session.bsession, self.address)

    def _handle_kernel_info_reply(self, msg):
        """handle kernel info reply

        sets protocol adaptation version
        """
        adapt_version = int(msg['content']['protocol_version'].split('.')[0])
        if adapt_version != major_protocol_version:
            self.session.adapt_version = adapt_version

    def _recv(self, **kwargs):
        # Listen for kernel_info_reply message to do protocol adaptation
        msg = ZMQSocketChannel._recv(self, **kwargs)
        if msg['msg_type'] == 'kernel_info_reply':
            self._handle_kernel_info_reply(msg)
        return msg

class BlockingIOPubChannel(ZMQSocketChannel):
    """The iopub channel which listens for messages that the kernel publishes.

    This channel is where all output is published to frontends.
    """
    def start(self):
        self.socket = make_iopub_socket(self.context, self.session.bsession, self.address)

class BlockingStdInChannel(ZMQSocketChannel):
    """The stdin channel to handle raw_input requests that the kernel makes."""
    msg_queue = None
    proxy_methods = ['input']

    def start(self):
        self.socket = make_stdin_socket(self.context, self.session.bsession, self.address)

ShellChannelABC.register(BlockingShellChannel)
IOPubChannelABC.register(BlockingIOPubChannel)
StdInChannelABC.register(BlockingStdInChannel)


class BlockingHBChannel(HBChannel):

    # This kernel needs quicker monitoring, shorten to 1 sec.
    # less than 0.5s is unreliable, and will get occasional
    # false reports of missed beats.
    time_to_dead = 1.

    def call_handlers(self, since_last_heartbeat):
        """ Pause beating on missed heartbeat. """
        pass
