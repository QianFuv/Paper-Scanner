# simple tokenizer (Upstream Project Notice)

This repository vendors prebuilt SQLite FTS5 `simple` tokenizer binaries for
Windows and Linux.

## Upstream Project

- Project: [simple tokenizer](https://github.com/wangfenjin/simple)
- Author: Wang Fenjin
- Original repository: https://github.com/wangfenjin/simple

Original project description (from the upstream README, translated):

> simple is a sqlite3 FTS5 extension that supports Chinese and Pinyin
> tokenization. It implements the WeChat mobile full-text-search approach for
> polyphonic Chinese characters and provides efficient Chinese/Pinyin search.
> On top of this, it also supports cppjieba-based tokenization for more
> accurate phrase matching.

## Bundled Artifacts in Paper Scanner

- `libs/simple-linux/libsimple-linux-ubuntu-latest/libsimple.so`
- `libs/simple-windows/libsimple-windows-x64/simple.dll`
- Related dictionary data under each platform directory

## License of Upstream simple

The upstream `simple` project uses a dual-license model: MIT or
GPL-3.0-or-later. Paper Scanner uses the upstream artifacts under the MIT
option.

- Upstream license file:
  https://github.com/wangfenjin/simple/blob/master/LICENSE
