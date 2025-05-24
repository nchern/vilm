import http.client
import json
import traceback

from contextlib import contextmanager
from datetime import datetime
from urllib.parse import urlparse

import pynvim


API_BASE_URL = 'http://localhost:11434'
API_TIMEOUT_SEC = 30

CHAT_HEIGHT = 20
CHAT_WIDTH = 80
INPUT_HEIGHT = 5


def _create_http_conn(api_url=API_BASE_URL, timeout=API_TIMEOUT_SEC):
    parsed = urlparse(api_url)
    host = parsed.hostname or 'localhost'
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    return http.client.HTTPConnection(host, port, timeout=timeout)


class LLMClient:
    def _do_request(self, method, url, headers={}, body=None):
        conn = _create_http_conn()
        conn.request(method, url, body=body, headers=headers)
        response = conn.getresponse()
        if response.status != 200:
            raise RuntimeError(f'Failed to fetch model list: HTTP {response.status}')
        return response

    def list_models(self):
        response = self._do_request('GET', '/api/tags')
        body = response.read().decode()
        data = json.loads(body)
        return [model["name"] for model in data.get("models", [])]

    def chat(self, messages, model):
        headers = {'Content-Type': 'application/json'}
        payload = json.dumps({
            'stream': True,
            'model': model,
            'messages': messages,
        })
        response = self._do_request('POST', '/api/chat', body=payload, headers=headers)
        for line in response:
            try:
                data = json.loads(line.decode())
                delta = data.get('message', {}).get('content', '')
                if delta:
                    yield delta
            except json.JSONDecodeError:
                continue


@pynvim.plugin
class Vilm:
    def __init__(self, nvim):
        self.nvim = nvim
        self.chat_buf = None
        self.input_buf = None
        self.chat_win = None
        self.input_win = None
        self.history = []
        self.client = LLMClient()
        self.current_model = self.nvim.vars.get('vilm_default_model', 'llama3.2:3b')

    def _log_message(self, msg):
        self.nvim.out_write(msg + "\n")

    def _editor_width(self):
        return self.nvim.options['columns']

    def _editor_height(self):
        return self.nvim.options['lines']

    def _set_buf_content(self, buf, lines):
        self.nvim.api.buf_set_lines(buf, 0, -1, False, lines)

    def _append_to_buf(self, buf, lines):
        self.nvim.api.buf_set_lines(buf, -1, -1, False, lines)

    def _create_floating_win(self, buf, height, width, row=None, col=None):
        if row is None:
            row = max((self._editor_height() - height) // 2, 0)
        if col is None:
            col = max((self._editor_width() - width) // 2, 0)
        opts = {
            'relative': 'editor',
            'width': width,
            'height': height,
            'col': col,
            'row': row,
            'style': 'minimal',
            'border': 'single'
        }
        return self.nvim.api.open_win(buf, True, opts)

    def _create_chat_buf(self):
        buf = self.nvim.api.create_buf(False, True)
        self.nvim.api.buf_set_option(buf, 'buftype', 'nofile')
        self.nvim.api.buf_set_option(buf, 'filetype', 'markdown')
        return buf

    def _bind_send_key(self):
        self.nvim.api.buf_set_keymap(
           self.input_buf, 'n', '<leader><CR>',':VILMSend<CR>',
            {'nowait': True, 'noremap': True, 'silent': True}
        )
        self.nvim.api.buf_set_keymap(
           self.input_buf, 'i', '<leader><CR>','<Esc>:VILMSend<CR>',
            {'nowait': True, 'noremap': True, 'silent': True}
        )

    def _bind_close_key(self, buf):
        self.nvim.api.buf_set_keymap(
            buf, 'n', '<leader>c', ':VILMCloseChat<CR>',
            {'nowait': True, 'noremap': True, 'silent': True}
        )
        self.nvim.api.buf_set_keymap(
            buf, 'i', '<leader>c', '<Esc>:VILMCloseChat<CR>',
            {'nowait': True, 'noremap': True, 'silent': True}
        )

    def get_last_reply(self):
        if self.history:
            return self.history[-1].get('content', '')
        return ''

    def _is_chat_open(self):
        return self.chat_win and self.nvim.api.win_is_valid(self.chat_win)

    def _copy_range(self, selected_range, src_buf, dst_buf):
        if selected_range and selected_range != (0, 0):
            start, end = selected_range
            lines = self.nvim.api.buf_get_lines(src_buf, start - 1, end, False)
            self._set_buf_content(dst_buf, lines)

    @pynvim.command('VILMChat', range='', nargs='0', sync=True)
    def open_chat(self, args, selected_range):
        if self._is_chat_open():
            self._log_message('Chat already open.')
            return
        # capture the current buffer BEFORE creating new ones
        orig_buf = self.nvim.current.buffer

        if not self.chat_buf or not self.nvim.api.buf_is_valid(self.chat_buf):
            self.chat_buf = self._create_chat_buf()
            self._bind_close_key(self.chat_buf)
        if not self.input_buf or not self.nvim.api.buf_is_valid(self.input_buf):
            self.input_buf = self._create_chat_buf()
            self._bind_close_key(self.input_buf)
            self._bind_send_key()

        col = max((self._editor_width() - CHAT_WIDTH) // 2, 0)
        chat_row = max((self._editor_height() - (CHAT_HEIGHT + INPUT_HEIGHT + 1)) // 2, 0)
        input_row = chat_row + CHAT_HEIGHT + 1

        self.chat_win = self._create_floating_win(
                self.chat_buf, CHAT_HEIGHT, CHAT_WIDTH, chat_row, col)
        self.input_win = self._create_floating_win(
                self.input_buf, INPUT_HEIGHT, CHAT_WIDTH, input_row, col)

        self.nvim.api.buf_set_option(self.chat_buf, 'modifiable', False)
        self.nvim.api.buf_set_option(self.input_buf, 'modifiable', True)

        self._copy_range(selected_range, orig_buf, self.input_buf)

    @pynvim.command('VILMCloseChat', nargs='0')
    def close_chat(self, args):
        for win in [self.chat_win, self.input_win]:
            try:
                if win and self.nvim.api.win_is_valid(win):
                    self.nvim.api.win_close(win, True)
            except Exception:
                pass
        self.chat_win = None
        self.input_win = None

    @contextmanager
    def _temporary_modifiable(self, buf):
        self.nvim.api.buf_set_option(self.chat_buf, 'modifiable', True)
        yield
        self.nvim.api.buf_set_option(self.chat_buf, 'modifiable', False)

    def _process_chat_response(self, message):
        line_idx = self.nvim.api.buf_line_count(self.chat_buf)
        full_response = ""
        try:
            for chunk in self.client.chat(self.history, self.current_model):
                full_response += chunk
                lines = full_response.splitlines()
                if full_response.endswith('\n'):
                    lines.append('')
                self.nvim.api.buf_set_lines(
                        self.chat_buf, line_idx, line_idx + len(lines), False, lines)
                total = self.nvim.api.buf_line_count(self.chat_buf)
                self.nvim.api.win_set_cursor(self.chat_win, [total, 0])
        except Exception as ex:
            trace = traceback.format_exc().splitlines()
            self._append_to_buf(self.chat_buf, [f'[Exception] {str(ex)}'] + trace)
        return full_response

    @pynvim.command('VILMSend', nargs='0')
    def send_message(self, args):
        if not self.input_buf or not self.chat_buf:
            self._log_message('Chat not open. Use :VILMChat first.')
            return

        lines = self.nvim.api.buf_get_lines(self.input_buf, 0, -1, False)
        message = '\n'.join(lines).strip()
        if not message:
            return
        self.history.append({'role': 'user', 'content': message})

        with self._temporary_modifiable(self.chat_buf):
            ts = datetime.now().strftime('%H:%M:%S')
            self._append_to_buf(self.chat_buf,
                    [f'@me ({ts}):'] + message.splitlines() + [''])
            self._append_to_buf(self.chat_buf, [f'@{self.current_model}:'])

            self._set_buf_content(self.input_buf, [])

            full_response = self._process_chat_response(message)
            if full_response.strip():
                self.history.append({'role': 'assistant', 'content': full_response})

            self._append_to_buf(self.chat_buf, [''])

    @pynvim.command('VILMPasteLast', nargs='0')
    def paste_last(self, args):
        if not self.get_last_reply():
            self._log_message('No previous LLM reply to paste.')
            return
        win = self.nvim.api.get_current_win()
        buf = self.nvim.api.win_get_buf(win)
        row = self.nvim.api.win_get_cursor(win)[0]
        lines = self.get_last_reply().splitlines()
        self.nvim.api.buf_set_lines(buf, row, row, False, lines)
        # Move cursor to first column after last inserted line
        new_row = row + len(lines)
        self.nvim.api.win_set_cursor(win, [new_row, len(lines[-1])])

    @pynvim.command('VILMModel', nargs='?', complete='customlist,VILMCompleteModels')
    def model_command(self, args):
        if not args:
            self._log_message(f'Current model: {self.current_model}')
        else:
            self.current_model = args[0]
            self._log_message(f'Model set to: {self.current_model}')

    @pynvim.command('VILMList', nargs='0')
    def list_models(self, args):
        try:
            models = self.client.list_models()
            if not models:
                self._log_message('No models found.')
                return
            qf_items = [{'filename': '', 'lnum': 1, 'col': 1, 'text': name} for name in models]
            self.nvim.call('setqflist', qf_items, 'r')
            self.nvim.command('copen')
        except Exception as ex:
            self._log_message(f'ERROR: failed to list models: {str(ex)}')

    @pynvim.command('VILMClearChat', nargs='0')
    def clean_chat(self, args):
        self.history = []
        if self.chat_buf and self.nvim.api.buf_is_valid(self.chat_buf):
            with self._temporary_modifiable(self.chat_buf):
                self._set_buf_content(self.chat_buf, [])

    @pynvim.command('VILMToggle', nargs='0', sync=True)
    def toggle_chat(self, args):
        if self._is_chat_open():
            self.close_chat(args)
        else:
            self.open_chat(args, (0, 0))

    @pynvim.command('VILMStatus', nargs='0', sync=True)
    def status(self, args):
        self._log_message(
            f'model: {self.current_model}; history_length: {len(self.history)}')

    @pynvim.function('VILMCompleteModels', sync=True)
    def complete_models(self, args):
        try:
            return self.client.list_models()
        except Exception as ex:
            # we do not really care about errors here: best effort
            self._log_message(f'ERROR: failed to fetch models: {str(ex)}')
            return []

    @pynvim.function('VILMStatusline', sync=True)
    def llm_status_line(self, args):
        return f'({self.current_model})'
