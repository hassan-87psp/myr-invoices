"""Exercise the actual registered validation handler without DB or API imports."""
import ast
import asyncio
from pathlib import Path

def main():
    tree=ast.parse((Path(__file__).resolve().parent/"backend/business_api.py").read_text())
    node=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=="redact_validation_error")
    assert len(node.decorator_list)==1
    assert ast.unparse(node.decorator_list[0])=="api.exception_handler(RequestValidationError)"
    node.decorator_list=[]
    def response(content,*,status_code,headers):
        return content,status_code,headers
    env={"JSONResponse":response}
    exec(compile(ast.Module(body=[node],type_ignores=[]),"<validation-handler>","exec"),env)
    class SensitiveError:
        def errors(self):
            raise AssertionError("Sensitive validation details must not be read")
        @property
        def body(self):
            raise AssertionError("Submitted request body must not be read")
    result=asyncio.run(env["redact_validation_error"](None,SensitiveError()))
    assert result==({"detail":"Invalid request data"},422,{"Cache-Control":"no-store","X-Content-Type-Options":"nosniff"})
    print("MYR_VALIDATION_REDACTION_OFFLINE_OK")

if __name__=="__main__":
    main()
