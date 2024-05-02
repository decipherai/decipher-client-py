import traceback
import requests
from flask import request_started, request_finished, got_request_exception
from flask import request, has_request_context
from datetime import datetime
import json
import builtins
import linecache
import functools

def safe_method(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            # Handle the exception or log it
            pass
    return wrapper

class DecipherMonitor:
    @safe_method
    def __init__(self, codebase_id, customer_id):
        self.codebase_id = codebase_id
        self.customer_id = customer_id
        #self.endpoint = "https://prod.getdecipher.com/api/exception_upload"
        self.endpoint = "http://localhost:3000/api/exception_upload"
        self.messages = []  # Initialize the messages list
        self.user = None
        self.response = None
        self.captured_exceptions = []
        self.uncaught_exception = None
        self.connect_to_signals()

    @safe_method
    def connect_to_signals(self):
        # Connect to Flask signals
        request_started.connect(self.before_request_handler)
        request_finished.connect(self.teardown_request_handler)
        got_request_exception.connect(self.capture_error_handler)

    @safe_method
    def before_request_handler(self, sender, **extra):
        self.exception_occurred = False
        if has_request_context():
            self.override_print()

    @safe_method
    def teardown_request_handler(self, sender, response, **extra):
        if has_request_context():
            self.restore_print()
            self.response = response;
            self.handleExceptions();

            #Reset state
            self.clear_messages()

    @safe_method
    def handleExceptions(self):
        if self.uncaught_exception:
            self.capture_error_with_response(self.response, self.uncaught_exception, True)
        if self.captured_exceptions:
            for exception in self.captured_exceptions:
                self.capture_error_with_response(self.response, exception)
        self.response = None
        self.user = None
        self.uncaught_exception = None
        self.captured_exceptions = []

    @safe_method
    def capture_error_with_response(self, response, exception, is_uncaught_exception=False):
        data = self.prepare_data(response, exception, is_uncaught_exception)
        self.send_to_decipher(data)

    @safe_method
    def capture_error_handler(self, sender, exception, **extra):
        self.uncaught_exception = exception
        if has_request_context():
            self.handleExceptions()

    @safe_method
    def get_request_body(self):
        request_body = None
        max_content_length = 10 * 1024 * 1024  # 10 MB
        if request.content_length and request.content_length < max_content_length:
            request_body = request.get_data(as_text=True)
            try:
                request_body = json.loads(request_body)
            except json.JSONDecodeError:
                request_body = request_body
        return request_body
    
    
    @safe_method
    def get_local_variables(self, frame):
        return {var: self.safe_repr(value) for var, value in frame.f_locals.items()}
    
    @safe_method
    def safe_repr(self, value):
        try:
            return repr(value)
        except Exception as e:
            return f"Error in repr: {e}"
    
    @safe_method
    def override_print(self):
        self.original_print = builtins.print
        builtins.print = self.custom_print

    @safe_method
    def restore_print(self, exception=None):
        builtins.print = self.original_print

    @safe_method
    def custom_print(self, *args, **kwargs):
        # Convert args to string and store the message
        message = ' '.join(str(arg) for arg in args)
        self.messages.append({
            "message": message,
            "level": "log",
            "timestamp": self.get_timestamp()
        })
        # Call the original print function
        self.original_print(*args, **kwargs)

    @safe_method
    def capture_error_with_exception(self, sender, **extra):
        if has_request_context():
            data = self.prepare_data()
            self.send_to_decipher(data)
        #stack_trace = "\n".join(traceback.format_stack()) if response else traceback.format_exc()

    @safe_method
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
    
    @safe_method
    def get_stack_trace_with_code(self, exception):
        if exception is None:
            return []
        
        tb = traceback.extract_tb(exception.__traceback__)
        formatted_trace = []
        context = 10
        for frame, line_number in [(tb_frame, tb_lineno) for tb_frame, tb_lineno in traceback.walk_tb(exception.__traceback__)]:
            filename = frame.f_code.co_filename
            function_name = frame.f_code.co_name
            start_line = max(1, line_number - context)
            code_context = self.get_code_context(filename, line_number, context)
            locals = self.get_local_variables(frame)
            formatted_trace.append({
                "file": filename,
                "line": line_number,
                "function": function_name,
                "code": code_context,
                "highlight_index": context,
                "start_line": start_line,
                "locals": locals,  # Add local variables to the trace
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


    @safe_method
    def append_error(self, error):
        self.captured_exceptions.append(error)

    @safe_method
    def prepare_data(self, response, exception, is_uncaught_exception=False):
        request_body = self.get_request_body()
        stack_trace = self.get_stack_trace_with_code(exception)
        #stack_trace = "\n".join(traceback.format_stack()) if response else traceback.format_exc()

        response_body = {}
        status_code = 500
        if response:
            status_code = response.status_code
            try:
                response_body = json.loads(response.get_data(as_text=True))
            except json.JSONDecodeError:
                response_body = response.get_data(as_text=True)

        data = {
            "codebase_id": self.codebase_id,
            "customer_id": self.customer_id,
            "timestamp": self.get_timestamp(),
            "error_stack": stack_trace,
            "request_url": request.url,
            "request_endpoint": request.endpoint,
            "request_headers": self.get_headers(request.headers),
            "request_body": request_body,
            "response_body": response_body,
            "status_code": status_code,
            "is_uncaught_exception": is_uncaught_exception,
            'messages': self.messages,
            'affected_user': self.user
        }
        return data

    @safe_method
    def get_timestamp(self):
        # To Do confirm this is right time format
        return datetime.utcnow().isoformat() + 'Z'
    
    @safe_method
    def get_headers(self, headers):
        return {header: value for header, value in headers.items()}
    
    @safe_method
    def clear_messages(self, exception=None):
        self.messages = []

    @safe_method
    def send_to_decipher(self, data):
        try:
            requests.post(self.endpoint, json=data)
        except requests.RequestException as e:
            pass

    @safe_method
    def capture_error(self, error):
        if has_request_context():
            self.capture_error_with_exception(request._get_current_object(), error)
        else:
            # Handle cases where there is no Flask request context
            pass

    @safe_method
    def safe_stringify(self, obj, indent=2):
        try:
            return json.dumps(obj, indent=indent, default=str)
        except TypeError:
            return str(obj)

    def set_user(self, user):
        if all(key in ['id', 'username', 'email'] for key in user):
            self.user = user
        
_decipher_monitor_instance = None

def init(codebase_id, customer_id):
    global _decipher_monitor_instance
    _decipher_monitor_instance = DecipherMonitor(codebase_id, customer_id)

def capture_error(error):
    if _decipher_monitor_instance:
        _decipher_monitor_instance.append_error(error)
    else:
        # Handle the case where DecipherMonitor is not initialized
        pass

def set_user(user):
    if _decipher_monitor_instance:
        _decipher_monitor_instance.set_user(user)
    else:
        # Handle the case where DecipherMonitor is not initialized
        pass