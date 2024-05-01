import traceback
import requests
import json
import builtins
from datetime import datetime
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import functools
import asyncio
import linecache
from contextvars import ContextVar
from fastapi import Request

current_request = ContextVar("decipher_current_request")
current_messages = ContextVar("current_messages", default=[])
current_user = ContextVar("current_user", default=None)

def safe_method(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
        except Exception as e:
            # Handle the exception or log it
            pass
    return wrapper

class DecipherMonitor(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, codebase_id: str, customer_id: str):
        super().__init__(app)
        self.codebase_id = codebase_id
        self.customer_id = customer_id
        self.endpoint = "https://prod.getdecipher.com/api/exception_upload"
        #self.endpoint = "http://localhost:3000/api/exception_upload"
        self.original_print = builtins.print
        builtins.print = self.custom_print

    async def __call__(self, scope, receive, send):
        # Setup or any preparation before handling the request
        request = Request(scope, receive=receive)
        request_token = current_request.set(request)
        messages_token = current_messages.set([])
        user_token = current_user.set(None)
        
        try:
            # Pass control to the next application in the stack
            await self.app(scope, receive, send)
        except Exception as exc:
            # Handle the exception (e.g., logging, modifying response to client)
            await self.capture_error_with_exception(request, exc, isManual = False)
            raise exc from None
        finally:
            current_request.reset(request_token)
            current_messages.reset(messages_token)
            current_user.reset(user_token)
            builtins.print = self.original_print

    def set_user(self, user):
        if all(key in ['id', 'username', 'email'] for key in user):
            current_user.set(user)

    async def capture_error_with_response(self, request: Request, response: Response):
        try:
            data = await self.prepare_data(request, response=response)
            await self.send_to_decipher(data)
        except Exception as e:
            pass

    async def capture_error_with_exception(self, request: Request, exception: Exception, isManual = True):
        try:
            data = await self.prepare_data(request, exception=exception, isManual = isManual)
            await self.send_to_decipher(data)
        except Exception as e:
            pass

    async def prepare_data(self, request: Request, response=None, exception=None, isManual = False):
        # request_body = await request.body()
        # try:
        #     request_body = json.loads(request_body.decode())
        # except json.JSONDecodeError:
        #     request_body = request_body.decode()  # Use raw body if JSON parsing fails

        # # Initialize response data
        response_body = {}

        if (isManual):
            status_code = 0
        else:
            status_code = 500  # Default to 500 unless a response object is provided

        if response:
            status_code = response.status_code
            try:
                response_body = json.loads(response.body.decode())
            except json.JSONDecodeError:
                response_body = response.body.decode()  # Use raw body if JSON parsing fails

        # Generate stack trace and local variables if an exception is provided
        stack_trace = []
        if exception:
            stack_trace = self.get_stack_trace_with_code(exception)

        # Prepare the data dictionary to be sent to the Decipher server
        data = {
            "codebase_id": self.codebase_id,
            "customer_id": self.customer_id,
            "timestamp": self.get_timestamp(),
            "error_stack": stack_trace,
            "request_url": str(request.url),
            "request_endpoint": str(request.url.path),
            "request_headers": dict(request.headers),
            "request_body": None,
            "response_body": response_body,
            "status_code": status_code,
            "is_uncaught_exception": exception is not None,
            'messages': current_messages.get(),
            'affected_user': current_user.get()
        }

        return data
    
    def get_timestamp(self):
        return datetime.utcnow().isoformat() + 'Z'
    
    def add_message(message: str, level: str = "info"):
        messages = current_messages.get()
        messages.append({"message": message, "level": level})
    
    def get_stack_trace_with_code(self, exception):
        if exception is None:
            return []
        
        tb = traceback.extract_tb(exception.__traceback__)
        formatted_trace = []
        context = 5  # Number of lines to include around the error line
        for frame, line_number in [(tb_frame, tb_lineno) for tb_frame, tb_lineno in traceback.walk_tb(exception.__traceback__)]:
            filename = frame.f_code.co_filename
            function_name = frame.f_code.co_name
            code_context = self.get_code_context(filename, line_number, context)
            locals = self.get_local_variables(frame)
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
        exception_type = type(exception).__name__
        exception_message = str(exception)
        if formatted_trace:
            last_trace = formatted_trace[-1]
            last_trace.update({
                "exception_type": exception_type,
                "exception_message": exception_message
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

    def get_local_variables(self, frame):
        return {var: repr(value) for var, value in frame.f_locals.items()}

    async def send_to_decipher(self, data):
        try:
            await asyncio.to_thread(requests.post, self.endpoint, json=data)
        except requests.RequestException as e:
            pass


    def custom_print(self, *args, **kwargs):
        messages = current_messages.get()
        message = ' '.join(str(arg) for arg in args)
        messages.append({
            "message": message,
            "level": "log",
            "timestamp": self.get_timestamp()
        })
        self.original_print(*args, **kwargs)

    def clear_messages(self):
        self.messages = []

_decipher_monitor_instance = None

def init(app, codebase_id, customer_id):
    global _decipher_monitor_instance
    _decipher_monitor_instance = DecipherMonitor(app, codebase_id, customer_id)
    app.add_middleware(DecipherMonitor, codebase_id=codebase_id, customer_id=customer_id)

def capture_error(error):
    request = current_request.get()
    if request and _decipher_monitor_instance:
        try:
            if asyncio.get_event_loop().is_running():
                # Asynchronous context: Use asyncio to handle it
                asyncio.create_task(_decipher_monitor_instance.capture_error_with_exception(request, error, isManual = True))
        except Exception as e:
            asyncio.run(_decipher_monitor_instance.capture_error_with_exception(request, error, isManual = True))

def set_user(user):
    request = current_request.get()
    if request and _decipher_monitor_instance:
        _decipher_monitor_instance.set_user(user)