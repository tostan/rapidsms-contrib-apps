#!/usr/bin/env python
# vim: ai ts=4 sts=4 et sw=4

import re
import rapidsms
from rapidsms.parsers import Matcher
from models import *
from apps.locations.models import *

class App(rapidsms.app.App):
    MSG = {
        "en": {
            "period": ". ",
            "denied": "Please join a village by texting us: #join villagename",
            "first-login": "Thank you for joining the village %(village)s",
            "register-fail": "Sorry, I couldn't register you.",
            "leave-success": "Good-bye from village %(village)s",
            "leave-fail": "'Leave' failed due to some unknown error.",
            "lang-set":    "I will now speak to you in English, where possible." },
            
        # TODO: move to an i18n app!
        "fr": {
            "period": ". ",
            "denied": "Svp join a village by texting us: #join villagename",
            "first-login": "Merci for joining the village %(village)s",
            "register-fail": "Je m'excuse, I couldn't register you.",
            "leave-success": "Au revoir from village %(village)s",
            "leave-fail": "'Partez' failed due to some unknown error.",
            "lang-set":    "I will now speak to you in French, where possible." },
        }
    
    
    def __str(self, key, reporter=None, lang=None):
        
        # if no language was explicitly requested,
        # inherit it from the reporter, or fall
        # back to english. because everyone in the
        # world speaks english... right?
        if lang is None:
            if reporter is not None:
                lang = reporter.language
            
            # fall back
            if lang is None:
                lang = "en"

        # look for an exact match, in the language
        # that the reporter has chosen as preferred
        if lang is not None:
            if lang in self.MSG:
                if key in self.MSG[lang]:
                    return self.MSG[lang][key]
        
        # not found in localized language. try again in english
        # TODO: allow the default to be set in rapidsms.ini
        return self.__str(key, lang="en") if lang != "en" else None
    
    
    def start(self):
        
        # fetch a list of all the backends
        # that we already have objects for
        known_backends = PersistantBackend.objects.values_list("slug", flat=True)
        
        # find any running backends which currently
        # don't have objects, and fill in the gaps
        for be in self.router.backends:
            if not be.slug in known_backends:
                self.info("Creating PersistantBackend object for %s (%s)" % (be.slug, be.title))
                PersistantBackend(slug=be.slug, title=be.title).save()
    
    
    def parse(self, msg):
        # fetch the persistantconnection object
        # for this message's sender (or create
        # one if this is the first time we've
        # seen the sender), and stuff the meta-
        # dta into the message for other apps
        conn = PersistantConnection.from_message(msg)
        msg.persistant_connection = conn
        msg.reporter = conn.reporter
        
        # store a handy dictionary, containing the most useful persistance
        # information that we have. this is useful when creating an object
        # linked to _something_, like so:
        # 
        #   class SomeObject(models.Model):
        #     reporter   = models.ForeignKey(Reporter, null=True)
        #     connection = models.ForeignKey(PersistantConnection, null=True)
        #     stuff      = models.CharField()
        #
        #   # this object will be linked to a reporter,
        #   # if one exists - otherwise, a connection
        #   SomeObject(stuff="hello", **msg.persistance_dict)
        if msg.reporter: msg.persistance_dict = { "reporter": msg.reporter }
        else:            msg.persistance_dict = { "connection": msg.persistant_connection }
        
        # log, whether we know who the sender is or not
        if msg.reporter: self.info("Identified: %s as %r" % (conn, msg.reporter))
        else:            self.info("Unidentified: %s" % (conn))
        
        # update last_seen, which automatically
        # populates the same property 
        conn.seen()
            
    
    def handle(self, msg):
        matcher = Matcher(msg)
        
        # TODO: this is sort of a lightweight implementation
        # of the keyworder. it wasn't supposed to be. maybe
        # replace it *with* the keyworder, or extract it
        # into a parser of its own
        map = {
            "join":  ["#join (whatever)"], # optionally: join village name m/f age
            #"*join":  ["join (whatever)"],
            #"#name":  ["add_name (whatever)"],
            #"*name":  ["add_name (whatever)"],
            #"#stats":  ["stats (letters) (numbers)"],
            #"*stats":  ["stats (letters) (numbers)"],
            "leave":  ["#leave"],
            #"*leave":  ["leave"],            
            "lang":  ["#lang (slug)"],
            #"*lang":  ["lang (slug)"]
        }
        
        # search the map for a match, dispatch
        # the message to it, and return/stop
        for method, patterns in map.items():
            if matcher(*patterns) and hasattr(self, method):  
                getattr(self, method)(msg, *matcher.groups)
                return True
        
        # no matches, so this message is not
        # for us; allow processing to continue
        return False
    
    
    def leave(self, msg):
        #try:
            reporter = Reporter.objects.all().get(identity=msg.connection.identity)
            lang = ''
            village = ''
            if reporter is not None:
                #default to deleting all persistent connections with the same identity
                #we can always come back later and make sure we are deleting the right backend
                pcs = PersistantConnection.objects.all().filter(identity=reporter.identity)
                for pc in pcs:
                    pc.delete()
                if len(reporter.language) > 0:
                    lang = reporter.language
                if reporter.location is not None:
                    if len(reporter.location.name) > 0:
                        village = reporter.location.name
                reporter.delete()
            
            msg.respond(
                self.__str("leave-success", lang=lang) % {
                 "village": village })
        
        # something went wrong - at the
        # moment, we don't care what
            """except:
                msg.respond(
                    self.__str("leave-fail", rep) 
                )
            """   
    
    def join(self, msg, village="default-village"):
        #try:
            # parse the name, and create a reporter
            # TODO: check for valid village/group/etc.
            rep = Reporter(location=Location(name=village), identity=msg.connection.identity)
            rep.save()
            
            # attach the reporter to the current connection
            msg.persistant_connection.reporter = rep
            msg.persistant_connection.save()
            
            msg.respond( self.__str("first-login", rep) % {"village": village } )
            return rep
            # TODO: remove this for production
            """except:
                msg.respond(
                    self.__str("register-fail", rep) 
                )
            """
            
        
    def lang(self, msg, code):
        # TODO: make this a decorator to be used in all functions
        # so that users don't have to register in order to get going
        err = None
        if msg.reporter is None:
            err = "denied"
            msg.reporter = self.join(msg)
        
        # if the language code was valid, save it
        # TODO: obviously, this is not cross-app
        if code in self.MSG:
            msg.reporter.language = code
            msg.reporter.save()
            resp = "lang-set"
        
        # invalid language code. don't do
        # anything, just send an error message
        else: resp = "bad-lang"
        
        # always send *some*
        # kind of response
        
        response = self.__str(resp, msg.reporter)
        if err is not None:
            response = response + self.__str(err, msg.reporter) + self.__str("period", msg.reporter)       
        msg.respond( response )
