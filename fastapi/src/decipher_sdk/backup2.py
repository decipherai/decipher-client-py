import traceback
import requests
import json
import builtins
from datetime import datetime
from fastapi import Request, Response, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send
import functools
import asyncio
import linecache

def safe_method(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
        except Exception as e:
            # Log the exception or handle it
            pass
    return wrapper

class DecipherMonitor(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, codebase_id: str, customer_id: str):
        super().__init__(app)
        self.codebase_id = codebase_id
        self.customer_id = customer_id
        self.endpoint = "https://prod.getdecipher.com/api/exception_upload"
        self.messages = []
        self.original_print = builtins.print
        builtins.print = self.custom_print


    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            if response.status_code != 200:
                # Handle non-200 responses, capture as error
                await self.capture_error_with_response(request, response)
        except Exception as e:
            # Handle exception, capture error data
            await self.capture_error_with_exception(request, e)
            raise HTTPException(status_code=500, detail="Internal Server Error")
        finally:
            builtins.print = self.original_print
            self.clear_messages()
        return response

    @safe_method
    async def capture_error_with_response(self, request: Request, response: Response):
        data = await self.prepare_data(request, response=response)
        await self.send_to_decipher(data)

    @safe_method
    async def capture_error_with_exception(self, request: Request, exception: Exception):
        data = await self.prepare_data(request, exception=exception)
        await self.send_to_decipher(data)

    @safe_method
    async def prepare_data(self, request: Request, response=None, exception=None):
        request_body = await request.body()
        try:
            request_body = json.loads(request_body.decode())
        except json.JSONDecodeError:
            request_body = request_body.decode()  # Use raw body if JSON parsing fails

        response_body = {}
        status_code = 500  # Default to 500 unless a response object is provided
        if response:
            status_code = response.status_code
            try:
                response_body = json.loads(response.body.decode())
            except json.JSONDecodeError:
                response_body = response.body.decode()  # Use raw body if JSON parsing fails

        stack_trace = []
        if exception:
            stack_trace = self.get_stack_trace_with_code(exception)

        data = {
            "codebase_id": self.codebase_id,
            "customer_id": self.customer_id,
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "error_stack": stack_trace,
            "request_url": str(request.url),
            "request_endpoint": str(request.url.path),
            "request_headers": dict(request.headers),
            "request_body": request_body,
            "response_body": response_body,
            "status_code": status_code,
            "is_uncaught_exception": exception is not None,
            "messages": self.messages
        }
        return data

    async def send_to_decipher(self, data):
        try:
            await requests.post(self.endpoint, json=data)
        except requests.RequestException as e:
            # Handle connection errors here
            pass

    def get_stack_trace_with_code(self, exception):
        tb = traceback.extract_tb(exception.__traceback__)
        formatted_trace = []
        context = 5  # Number of lines to include around the error line
        for frame, line_number in [(tb_frame, tb_lineno) for tb_frame, tb_lineno in traceback.walk_tb(exception.__traceback__)]:
            filename = frame.f_code.co_filename
            function_name = frame.f_code.co_name
            code_context = self.get_code_context(filename, line_number, context)
            locals = {var: repr(value) for var, value in frame.f_locals.items()}
            formatted_trace.append({
                "file": filename,
                "line": line_number,
                "function": function_name,
                "code": code_context,
                "highlight_index": context,
                "start_line": max(1, line_number - context),
                "locals": locals,
            })

        # Add the exception type and message to the last trace
        if formatted_trace:
            formatted_trace[-1].update({
                "exception_type": type(exception).__name__,
                "exception_message": str(exception)
            })

        return formatted_trace

    def get_code_context(self, filename, line_number, context=5):
        start_line = max(1, line_number - context)
        end_line = line_number + context
        code_context = []
        
        for i in range(start_line, end_line + 1):
            try:
                line = linecache.getline(filename, i).rstrip()
                code_context.append(line)
            except Exception as e:
                code_context.append("Error reading line: " + str(e))
        
        linecache.clearcache()
        return code_context
    
    def custom_print(self, *args, **kwargs):
        message = ' '.join(str(arg) for arg in args)
        self.messages.append({
            "message": message,
            "level": "log",
            "timestamp": datetime.utcnow().isoformat() + 'Z'
        })
        self.original_print(*args, **kwargs)

    def clear_messages(self):
        self.messages = []

_decipher_monitor_instance = None

def init(app, codebase_id, customer_id):
    global _decipher_monitor_instance
    _decipher_monitor_instance = DecipherMonitor(app, codebase_id, customer_id)
    app.add_middleware(DecipherMonitor, codebase_id=codebase_id, customer_id=customer_id)

async def capture_error(request: Request, error):
    if _decipher_monitor_instance:
        await _decipher_monitor_instance.capture_error_with_exception(request, error)