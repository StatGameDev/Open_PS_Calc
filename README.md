# PS Calc

A pre-renewal Ragnarok Online damage calculator. Shows the full damage pipeline step by
step, with each calculation citing the exact Hercules emulator source function.

Supports standard pre-renewal servers and [Payon Stories](https://discord.gg/payonstories).

---

## Quick Start

Python 3.13 or later is required — download from [python.org](https://www.python.org/downloads/).

**Windows:** double-click `run.bat`.  
**Linux / macOS:** run `./run.sh` in a terminal.

Both scripts install dependencies and launch the app automatically.

---

## Running manually

```
pip install -r requirements.txt
python main.py
```

---

## Formula accuracy

All damage formulas are derived from the
[Hercules](https://github.com/HerculesWS/Hercules) pre-renewal source — specifically
`#ifndef RENEWAL` blocks and the `#else` branches of `#ifdef RENEWAL` / `#else` /
`#endif` sequences. Every pipeline step cites the specific source file and function.

If you find a discrepancy between the calculator output and in-game results, open an
issue with the skill name, input values, and observed damage.

---

## Status

Active development. First public release. Expect gaps in skill coverage; see open issues.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

[MIT](LICENSE)
