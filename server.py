import time
import socket
import threading
import SocketServer
from DB import UserDB
from DB import MessageDB

# register constants
USER_ALREADY_EXISTS = '1'
YOU_ARE_REGISTERED = '2'

# login constants
SUCCESSFULLY_AUTHENTICATED = '0'
NO_SUCH_USER_EXISTS = '1'
PASSWORD_WRONG = '2'
USER_ALREADY_LOGGED_IN = '3'
PASSWORD_WRONG_YOU_ARE_BLOCKED = '4'
YOU_HAVE_BEEN_BLOCKED = '5'

FAILED = 0
SUCCESS = 1
MAX_ATTEMPTS = 3
BLOCK_TIME = 60

PRIVATE = 'private'
BROADCAST = 'broadcast'
LOGOUT = 'logout'


class ThreadedTCPRequestHandler(SocketServer.BaseRequestHandler):
    def handle(self):
        # Receive special userPacket for login/register
        userPacket = eval(self.request.recv(1024))
        userSocket = self.request.getpeername()

        # get the dict for the user
        userDB = UserDB()
        userDict = userDB.getUserData(userPacket['username'])
        userBlocked = userDB.getUserBlockList(userPacket['username'])

        status = FAILED
        if userPacket['purpose'] == 'register':
            status = self.handleRegister(userPacket, userDB, userDict)
        elif userPacket['purpose'] == 'login':
            status = self.handleLogin(userPacket, userDB, userDict, userBlocked, userSocket)

        if status == SUCCESS:

            #TODO: what happens to loop after logging out
            messageDB = MessageDB()
            while True:
                self.handleChat(userDB, userDict, messageDB)


    def handleRegister(self, userPacket, userDB, userDict):
        if userDict:
            self.request.sendall(USER_ALREADY_EXISTS)
            return FAILED
        else:
            # register
            userDB.register(userPacket['username'], userPacket['password'])
            self.request.sendall(YOU_ARE_REGISTERED)

            # user is auto-logged-in if registration is success
            return SUCCESS

    def handleLogin(self, userPacket, userDB, userDict, userBlocked, userSocket):
        if not userDict:
            self.request.sendall(NO_SUCH_USER_EXISTS)
            return FAILED
        elif userBlocked:
            # Block check: if next possible login time is in future
            if userBlocked['initialFailedLoginTime'] > time.time():
                self.request.sendall(YOU_HAVE_BEEN_BLOCKED
                                     + " " + str(userBlocked['initialFailedLoginTime']))
                return FAILED

        # check password match
        if userDict['password'] == userPacket['password']:
            # check already logged in
            # if userDict['isLoggedIn']:
            #     self.request.sendall(USER_ALREADY_LOGGED_IN)
            #     return FAILED
            # else:
            self.request.sendall(SUCCESSFULLY_AUTHENTICATED)
            userDict['isLoggedIn'] = True
            userDict['socket'] = userSocket
            userDB.updateUserData(userDict)
            return SUCCESS
        else:
            if not userBlocked or (time.time() - userBlocked['initialFailedLoginTime'] > 60):
                if not userBlocked:
                    userBlocked = {'username': userPacket['username']}
                userBlocked['numAttempts'] = 1
                userBlocked['initialFailedLoginTime'] = time.time()
            else:
                userBlocked['numAttempts'] += 1

            if userBlocked['numAttempts'] > MAX_ATTEMPTS:
                # block user for BLOCK_TIME
                userBlocked['initialFailedLoginTime'] = time.time() + BLOCK_TIME
                self.request.sendall(PASSWORD_WRONG_YOU_ARE_BLOCKED +
                                     " " + str(userBlocked['initialFailedLoginTime']))
            else:
                self.request.sendall(PASSWORD_WRONG)

            # Update userBlockList
            userDB.updateUserBlockList(userBlocked)
            return  FAILED

    # TODO 1:
    def handleUnread(self, userDict, messageDB):
        # search in DB(messageDB) for old messages: messageDB.getUnreadMessages(username)
        # if present send it to client
        #   -- and update the DB(messageDB) messageDB.removeUnreadMessage(username)
        pass

    # TODO 2.0:
    def handleChat(self, userDB, userDict, messageDB):
        # messageType = PRIVATE
        # first receive type of message(broadcast/private/logout), length of message
        # update messageType
        try:
            msgAck = self.request.recv(1024)
            if not msgAck:
                return
            msgAck = eval(msgAck)
            self.request.sendall('1232')
            print msgAck
            if msgAck['cmd'] == 'send':

                if msgAck['msgType'] == PRIVATE:
                    msgPacket = eval(self.request.recv(msgAck['msgLen']))
                    self.handlePrivateMessage(userDB, userDict, msgPacket, messageDB)

                elif msgAck['msgType'] == BROADCAST:
                    msgPacket = eval(self.request.recv(msgAck['msgLen']))
                    self.handleBroadcastMessage(userDB, userDict, msgPacket, messageDB)

            elif msgAck['cmd'] == LOGOUT:
                    self.handleLogout(UserDB, userDict)

            else:
                pass

        except socket.error, e:
            pass


    # TODO 2.1:
    def handlePrivateMessage(self, userDB, userDict, msgPacket, messageDB, broadcast=False):
        # check toUser exists or not
        # check whether toUser is logged in or not
        # if logged in send him the message using userDB.getUserData(toUser)['socket']
        # otherwise store it in DB [toUser, fromUser, message, time?]
        #   -- messageDB.addUnreadMessage(toUser, fromUser, message)
        toUser = msgPacket['toUser']
        receiver = userDB.getUserData(toUser)
        if not receiver:
            return

        msgType = PRIVATE
        if broadcast:
            msgType = BROADCAST
        msgPacket['msgType'] = msgType

        if receiver['isLoggedIn']:
            # write to socket
            #TODO: Read host and port correctly
            host, port = receiver['socket'][0], receiver['socket'][1] 
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.connect((host, port))
                msgAck = {'cmd':'send', 'msgLen':len(msgPacket), 'msgType':msgType}
                s.sendall(str(msgAck))
                s.sendall(str(msgPacket))
                print receiver['isLoggedIn']
                s.close()
            except socket.error:
                self.handleLogout(userDB, receiver)
                self.handlePrivateMessage(userDB, userDict, msgPacket, messageDB)

        else:
            messageDB.addUnreadMessage(toUser, userDict['username'], msgPacket)


    # TODO 2.2:
    def handleBroadcastMessage(self, userDB, userDict, msgPacket, messageDB):
        # get all usernames/sockets who are loggedin: userDB.getAllUsersLoggedIn()
        #   -- and send them message
        activeUsers = userDB.getAllUsersLoggedIn()
        for receiver in activeUsers:
            msgPacket['toUser'] = receiver
            self.handlePrivateMessage(userDB, userDict, msgPacket, messageDB, broadcast=True)

    # TODO 2.3:
    def handleLogout(self, userDB, userDict):
        userDict['isLoggedIn'] = False
        userDB.updateUserData(userDict)

        pass

class ThreadedTCPServer(SocketServer.ThreadingMixIn, SocketServer.TCPServer):
    pass

def main():
    HOST = socket.gethostname()
    PORT = 9999
    server = ThreadedTCPServer((HOST, PORT), ThreadedTCPRequestHandler)

    # start a thread with the server.
    # the thread will then start one more thread for each request.
    server_thread = threading.Thread(target=server.serve_forever)
    # exit the server thread when the main thread terminates
    server_thread.daemon = True
    server_thread.start()   # equivalent to serversocket.listen()

    while True:
        # do nothing
        count = 1

    server.shutdown()


if __name__ == '__main__':
    main()
