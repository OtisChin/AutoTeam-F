#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, urllib.parse, time
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    order_id='MOCK-ORDER-12345'
    def log_message(self, fmt, *args): return
    def _json(self, status, obj):
        body=json.dumps(obj).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        length=int(self.headers.get('content-length','0') or 0)
        raw=self.rfile.read(length).decode('utf-8','replace') if length else ''
        if self.path == '/v1/oauth2/token':
            auth=self.headers.get('authorization','')
            if not auth.startswith('Basic '):
                return self._json(401, {'error':'invalid_client'})
            return self._json(200, {'access_token':'mock-access-token','token_type':'Bearer','expires_in':3600})
        if self.path == '/v2/checkout/orders':
            try: req=json.loads(raw or '{}')
            except Exception: req={}
            ec=(req.get('payment_source') or {}).get('paypal',{}).get('experience_context',{})
            ret=ec.get('return_url','http://127.0.0.1:8765/return')
            approve=f"{ret}?token={self.order_id}&PayerID=MOCKPAYER"
            return self._json(201, {'id':self.order_id,'status':'PAYER_ACTION_REQUIRED','links':[{'href':approve,'rel':'payer-action','method':'GET'}]})
        if self.path == f'/v2/checkout/orders/{self.order_id}/capture':
            return self._json(201, {'id':self.order_id,'status':'COMPLETED','purchase_units':[{'payments':{'captures':[{'id':'MOCK-CAPTURE-1','status':'COMPLETED'}]}}]})
        return self._json(404, {'error':'not_found','path':self.path})

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--host',default='127.0.0.1'); ap.add_argument('--port',type=int,default=18765)
    ns=ap.parse_args(); HTTPServer((ns.host,ns.port),Handler).serve_forever()
