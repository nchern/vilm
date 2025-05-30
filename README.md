# VILM - Neovim LLM interfacr Plugin

Vi(m) L(L)Ms.

VILM is a lightweight interface for using language models directly from your Neovim editor.
It aims to stay minimal while exploring UI patterns and workflow ideas to enrich the Vim experience.

## Public Commands

- `:VILMChat` - opens a floating LLM chat window, optionally pre-filled with selected text.
- `:VILMCloseChat` - closes the chat interface if open.
- `:VILMSend` - sends the input message to the LLM and displays the response.
- `:VILMPasteLast` - pastes the last LLM response at the current cursor location.
- `:VILMModel [model_name]` - sets or displays the current LLM model.
- `:VILMList` - lists available models in the quickfix list.
- `:VILMClearChat` - resets message history and clears chat buffer.
- `:VILMToggle` - toggles the chat interface on or off.

## Key Mappings

- `<leader><Enter>` - send a message via `:VILMSend` when chat is active.
- `<leader>c` - closes the chat via `:VILMCloseChat`).

## Installation
Via `vim-plug`:
```
Plug 'nchern/vilm', { 'do': ':UpdateRemotePlugins' }
```

## Implementation notes

Currently VILM talks to LLMs via [Ollama](https://ollama.com)
[API](https://github.com/ollama/ollama/blob/main/docs/api.md) and expects
Ollama service listening on `localhost:11434`

## Screenshots
![Open chat window](/assets/vim-open-chat.png)
