#!/usr/bin/env node
// Decode a .bgcode file to ASCII G-code text using the official libbgcode WASM build.
// Reads binary from stdin or a file path argument, writes decoded text to stdout.
// Exit 0 on success, 1 on any failure with the reason on stderr.

"use strict";

const path = require("path");
const fs = require("fs");

const wasmDir = path.resolve(__dirname, "..", "wasm");

// Load the Emscripten module relative to the vendored assets.
const wasmJs = path.join(wasmDir, "bgcode.js");
if (!fs.existsSync(wasmJs)) {
    process.stderr.write(`bgcode-decode: WASM loader not found at ${wasmJs}\n`);
    process.exit(1);
}

const Module = require(wasmJs);

Module.onRuntimeInitialized = () => {
    let input;
    try {
        if (process.argv.length > 2) {
            input = fs.readFileSync(process.argv[2]);
        } else {
            input = fs.readFileSync(0); // stdin
        }
    } catch (e) {
        process.stderr.write(`bgcode-decode: cannot read input: ${e.message}\n`);
        process.exit(1);
    }

    const ab = input.buffer.slice(input.byteOffset, input.byteOffset + input.byteLength);

    try {
        const text = Module.bgcode2ascii_and_verify(ab);
        if (!text || text.length === 0) {
            process.stderr.write("bgcode-decode: decoder returned empty output\n");
            process.exit(1);
        }
        process.stdout.write(text);
    } catch (e) {
        process.stderr.write(`bgcode-decode: decode failed: ${e.message || e}\n`);
        process.exit(1);
    }
};

// onRuntimeInitialized fires synchronously after the module loads; the decode
// runs and process exits inside it. No timer needed — the timeout was firing
// after successful output because Node's event loop held the process alive.
