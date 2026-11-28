"""Secret-free tests of candidate security primitives extracted from source.
No database, provider, or VPS calls; not a substitute for integration tests.
"""
import ast
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock
from datetime import date,datetime,timezone
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent/"backend"
def tree(name):
    return ast.parse((ROOT/name).read_text())
def node(name,func):
    return next(n for n in tree(name).body if isinstance(n,ast.FunctionDef) and n.name==func)
def load(name,funcs,env):
    for func in funcs:
        n=node(name,func)
        n.decorator_list=[]
        exec(compile(ast.Module(body=[n],type_ignores=[]),name,"exec"),env)
    return env

class HTTPException(Exception):
    def __init__(self,status_code,detail,headers=None):
        self.status_code=status_code
        self.headers=headers or {}

def denied(fn,status):
    try: fn()
    except HTTPException as e:
        assert e.status_code==status
        return e
    raise AssertionError("Request unexpectedly permitted")

def rate_tests():
    now=[1000]
    buckets=OrderedDict()
    env=load("business_native_auth.py",["throttle","guard"],{
        "monotonic":lambda:now[0],"LOCK":Lock(),"BUCKETS":buckets,"HTTPException":HTTPException,
        "os":SimpleNamespace(environ={"MYR_PRODUCTION_RELEASE":"fixture"}),
        "ipaddress":__import__("ipaddress"),"production_release":lambda:True})
    throttle=env["throttle"];guard=env["guard"]
    throttle(("test",),2,60);throttle(("test",),2,60)
    assert denied(lambda:throttle(("test",),2,60),429).headers["Retry-After"]=="60"
    now[0]+=60
    throttle(("test",),2,60)
    denied(lambda:guard(SimpleNamespace(client=SimpleNamespace(host="192.0.2.1"),headers={}),"login"),403)
    request=SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"),headers={"x-real-ip":"192.0.2.2"})
    denied(lambda:guard(SimpleNamespace(client=request.client,headers={}),"login"),403)
    for i in range(4):
        for j in range(30):guard(request,"fixture-"+str(i))
    denied(lambda:guard(request,"different-action"),429)
    now[0]+=60
    guard(request,"different-action")

def authorization_tests():
    env=load("business_api.py",["owner_company","admin_identity"],{"HTTPException":HTTPException})
    conn=Mock()
    profile={"email":"owner@example.invalid","is_platform_admin":False}
    conn.execute.return_value.fetchone.return_value=None
    denied(lambda:env["owner_company"](conn,profile,"other-tenant",True),404)
    sql,args=conn.execute.call_args.args
    assert "c.id=%s" in sql and "m.email=%s" in sql and "m.status='active'" in sql
    assert "m.role=ANY(%s)" in sql and "FOR UPDATE OF c FOR SHARE OF m" in sql
    assert args==("other-tenant",profile["email"],["Owner"])
    conn.reset_mock()
    denied(lambda:env["owner_company"](conn,{**profile,"is_platform_admin":True},"other-tenant"),403)
    conn.execute.assert_not_called()
    env["identity"]=lambda *args:profile
    denied(lambda:env["admin_identity"](conn,None),403)
    env["identity"]=lambda *args:{**profile,"is_platform_admin":True}
    assert env["admin_identity"](conn,None)["is_platform_admin"] is True
    workspace=ast.unparse(node("business_api.py","workspace"))
    assert workspace.count("company_id=ANY(%s)")>=3
    assert "m.email=%s" in workspace and "m.status='active'" in workspace
    admin=ast.unparse(node("business_admin.py","set_company"))
    assert "AND (NOT disabled OR password_hash IS NULL) FOR SHARE" in admin
    for route,action in (("public_link_read","public-link-read"),("public_link_submit","public-link-submit")):
        body=node("business_api.py",route).body
        assert ast.unparse(body[0])=="require_cutover()"
        assert ast.unparse(body[1])=="native.guard(request, '"+action+"')"

def session_tests():
    login=ast.unparse(node("native_auth.py","authenticate"))
    assert "WHERE email = %s FOR SHARE" in login
    reset=ast.unparse(node("account_lifecycle.py","finish_password"))
    assert "WHERE id=%s FOR UPDATE" in reset
    assert "used_at IS NULL" in reset and "expires_at>now()" in reset
    assert "UPDATE myr_native.sessions SET revoked_at=now()" in reset
    session=ast.unparse(node("native_auth.py","session_user"))
    assert all(s in session for s in ("s.revoked_at IS NULL","s.expires_at>now()","NOT u.disabled"))
    cookie=ast.unparse(node("business_native_auth.py","login"))
    assert all(s in cookie for s in ("httponly=True","secure=True","samesite='strict'"))

class Rejected(Exception):pass
def require(ok,message):
    if not ok:raise Rejected(message)
def payment_tests():
    roles=("Owner","Admin","Accountant")
    invoice={"id":"i1","docType":"01","appStatus":"Draft","lhdn":{"status":"Not Submitted"},"payments":[]}
    previous={"invoices":[invoice]}
    conn=Mock()
    conn.execute.return_value.fetchone.return_value=None
    def lock(conn,uid,email,cid,roles):
        assert roles==("Owner","Admin","Accountant")
        return 1,previous
    persist=Mock()
    env=load("native_payment_ops.py",["add_payment"],{"require":require,"text_id":lambda x:isinstance(x,str) and bool(x),
        "encode":str,"date":date,"datetime":datetime,"ZoneInfo":ZoneInfo,"timezone":timezone,
        "lock_company":lock,"PAYMENT_ROLES":roles,"record_rows":lambda x,k:x[k],
        "total_sen":lambda x:1000,"persist":persist,"WriteRejected":Rejected})
    pay=env["add_payment"]
    p={"id":"p1","amount":500,"date":datetime.now(ZoneInfo("Asia/Kuala_Lumpur")).date().isoformat(),"method":"Cash"}
    result=pay(conn,"u","owner@example.invalid","c","i1",p)
    assert result["existing"] is False and persist.call_count==1
    invoice["payments"]=result["invoice"]["payments"]
    assert pay(conn,"u","owner@example.invalid","c","i1",p)["existing"] is True and persist.call_count==1
    for bad in ({**p,"amount":501},{**p,"id":"p2","amount":501}):
        try:pay(conn,"u","owner@example.invalid","c","i1",bad)
        except Rejected:pass
        else:raise AssertionError("Invalid payment accepted")
    assert persist.call_count==1
    lock_src=ast.unparse(node("native_payment_ops.py","lock_company"))
    assert "m.role=ANY(%s)" in lock_src and "list(roles)" in lock_src and "FOR UPDATE OF c" in lock_src

if __name__=="__main__":
    rate_tests();authorization_tests();session_tests();payment_tests()
    print("MYR_SECURITY_REGRESSION_OFFLINE_OK")
