## Kamailio - equivalent of routing blocks in Python
from queue import Full
import sys
import Router.Logger as Logger
import KSR as KSR
from concurrent import futures
import logging

import grpc

def dumpObj(obj):
    for attr in dir(obj):
        # KSR.info("obj.%s = %s\n" % (attr, getattr(obj, attr)));
        Logger.LM_INFO("obj.%s = %s\n" % (attr, getattr(obj, attr)));

# global function to instantiate a kamailio class object
# -- executed when kamailio app_python module is initialized
def mod_init():
    KSR.info("===== from Python mod init\n")
#    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10));
    return kamailio();

# -- {start defining kamailio class}
class kamailio:
    def __init__(self):
        KSR.info('===== kamailio.__init__\n');
        self.user_states = {}
    
    # executed when kamailio child processes are initialized
    def child_init(self, rank):
        KSR.info('===== kamailio.child_init(%d)\n' % rank)
        return 0

    # SIP request routing
    # -- equivalent of request_route{}
    def ksr_request_route(self, msg):
        KSR.info("===== request - from kamailio python script\n");
        KSR.info("===== method [%s] r-uri [%s]\n" % (KSR.pv.get("$rm"),KSR.pv.get("$ru")));
        domain = KSR.pv.get("$rd")  # $rd é o domínio da Request-URI
        contact_header = KSR.pv.get("$hdr(Contact)")
        
        # Rejeitar se o domínio não for 'acme.pt'
        
        to_uri = KSR.pv.get("$tu")  # Obtém o destinatário (to URI)
        caller_uri = KSR.pv.get("$fu") # Obtém o caller (to URI)
        
        #if KSR.pv.get("$rm") == "REGISTER":
        if KSR.is_REGISTER():
            if domain != "grupo8.pt":
                KSR.info("===== Rejecting REGISTER: Domain [%s] is not allowed =====\n" % domain)
                KSR.sl.send_reply(403, "Forbidden - Domain Not Allowed")
                return 1  # Termina o processamento aqui
            KSR.info("===== Accepting REGISTER: Domain [%s] =====\n" % domain)
            expires = int(contact_header.split("expires=")[1].split(";")[0])
            if expires > 0:
                self.user_states[caller_uri] = 0
                KSR.info("===== User [%s] registered with state [0] =====\n" % caller_uri)      
                KSR.registrar.save("location", 0)
                return 1
            else: 
                self.user_states[caller_uri] = None
                KSR.info("===== User unregistered successfully =====\n")      
                KSR.registrar.save("location", 0)
                return 1
        
        # Invite
        if KSR.is_INVITE():
            if domain != "grupo8.pt":
                KSR.info("===== Rejecting REGISTER: Domain [%s] is not allowed =====\n" % domain)
                KSR.sl.send_reply(403, "Forbidden - Domain Not Allowed")
                return 1  # Termina o processamento aqui
            KSR.info("===== Processing INVITE for domain [%s] =====\n" % domain)
            
            # Verifica se o destinatário é "sip:conference@grupo8.pt"
            if to_uri == "sip:conference@grupo8.pt":
                KSR.info("===== Rewriting INVITE to sip:conference@127.0.0.1:5090 =====\n")
                self.user_states[caller_uri] = 1
                KSR.pv.sets("$ru", "sip:conference@127.0.0.1:5090")  # Define o novo destino no header "To"
                KSR.info("===== User [%s] registered with state [1] =====\n" % caller_uri)
                KSR.rr.record_route()      
                KSR.tm.t_relay()  # Reencaminha a chamada para o novo destino             
                return 1  # Terminar processamento
            
            state = self.user_states.get(to_uri, 0)
            KSR.info("===== Destination [%s] state is [%d] =====\n" % (to_uri, state))

            if state == 1:
                KSR.info("===== Destination is in a conference, redirecting to the conference =====\n")
                KSR.pv.sets("$ru", "sip:conference@127.0.0.1:5090")
                KSR.rr.record_route()
                KSR.tm.t_relay()
                self.user_states[caller_uri] = 1
                return 1
            elif state == 2:
                KSR.info("===== Destination is busy right now =====\n")
                KSR.pv.sets("$ru", "sip:announcement@127.0.0.1:5080")
                KSR.info("===== Alô do Anúncio!")
                KSR.rr.record_route()
                KSR.tm.t_relay()
                self.user_states[caller_uri] = 2
                return 1
            elif state == 0:
                if KSR.registrar.lookup("location") == 1:  # Verificar registo do utilizador na base de dados
                    KSR.info("===== Destination found. Forwarding the call =====\n")
                    KSR.rr.record_route()
                    KSR.tm.t_relay()  # Reencaminha a chamada para o destino
                    self.user_states[caller_uri] = 2
                    self.user_states[to_uri] = 2
                    KSR.info("===== Users [%s], [%s] with state [2] =====\n" % (caller_uri, to_uri))      
                    return 1  # Terminar processamento
                else:
                    KSR.info("===== Destination not found in location table =====\n")
                    KSR.sl.send_reply(404, "User Not Found")
                    return 1  # Terminar processamento
            return 1
    
        if (msg.Method == "ACK"):
            KSR.info("ACK R-URI: " + KSR.pv.get("$ru") + "\n")
            KSR.rr.loose_route()
            KSR.tm.t_relay()
            return 1
        
        if (msg.Method == "BYE"):
            KSR.info("BYE R-URI: " + KSR.pv.get("$ru") + "\n")
            KSR.registrar.lookup("location")
            KSR.rr.loose_route()
            KSR.tm.t_relay()
            
            caller_state = self.user_states.get(caller_uri, 0)
            to_state = self.user_states.get(to_uri, 0)
            if caller_state == 2 and to_state == 2:
                KSR.info("===== Call between [%s] and [%s] ended. Resetting both states to [0] =====\n" % (caller_uri, to_uri))
                self.user_states[caller_uri] = 0
                self.user_states[to_uri] = 0
            elif caller_state == 1:
                KSR.info("===== User [%s] left the conference. Setting state to [0] =====\n" % caller_uri)
                self.user_states[caller_uri] = 0
            else:
                KSR.info("===== User [%s] ended call. Setting state to [0] =====\n" % caller_uri)
                self.user_states[caller_uri] = 0
        return 1
    
    def ksr_reply_route(self, msg):
        KSR.info("===== response - from kamailio python script\n")
        KSR.info("      Status is:"+ str(KSR.pv.get("$rs")) + "\n");
        return 1

    def ksr_onsend_route(self, msg):
        KSR.info("===== onsend route - from kamailio python script\n")
        KSR.info("      %s\n" %(msg.Type))
        return 1