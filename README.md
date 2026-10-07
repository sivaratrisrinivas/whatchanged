# whatchanged

## What

`whatchanged FROM TO` compares two published versions of the [`elevenlabs`](https://pypi.org/project/elevenlabs/) Python SDK and writes a Markdown report with two kinds of change.

- **Surface changes.** Methods and parameters that were added, removed, moved or retyped.
- **Wire changes.** The same call sends a different HTTP request, whether in path, query, headers or body encoding.

Here is one call in two versions.

```python
client.voices.update("vid", name="n", labels='{"accent": "british"}')
```

| version | multipart field `labels` |
|---|---|
| 2.54.0 | `{"accent": "british"}` |
| 2.59.0 | `"{\"accent\": \"british\"}"` |

2.59.0 JSON-encodes the string a second time. Passing a `dict` raises `TypeError` in 2.54.0 and works in 2.59.0. The type alias was renamed from `VoicesUpdateRequestLabels` to `EditVoiceRequestLabels`, but both resolve to `Union[Dict[str, str], str]`, so the report lists the wire change and no type change.

## Why

Fern regenerates this SDK about every week, and the release notes mostly say "SDK regeneration". [elevenlabs/elevenlabs-python#832](https://github.com/elevenlabs/elevenlabs-python/issues/832) describes an app that broke on a wire change those notes never mentioned. A version has about 2,500 generated files, so nobody finds that kind of change by reading the diff.

Running the tool on 2.54.0 and 2.59.0 found 40 methods whose requests changed. One example is 34 methods that now send an empty `{}` JSON body where 2.54.0 sent none.

## How

Install it and compare two versions.

```console
$ pip install -e .
$ whatchanged 2.54.0 2.59.0 -o report.md
$ whatchanged 2.71.0 3.0.0a1 --guide v3
```

The second command also lists changes that the [v3 upgrade guide](https://github.com/elevenlabs/elevenlabs-python/wiki/v3-upgrade-guide) does not mention. The report calls them possible additions, not errors.

The tool works in five steps.

1. It installs each version into its own folder with `pip install --target .cache/env/<version>` and caches it, so `elevenlabs` never touches your environment.
2. A subprocess (`python -I`) loads that folder, builds the client on an `httpx.MockTransport` and walks every public method of the sync client. It records each signature with resolved types, so a renamed alias is not a type change.
3. It calls each method with required params only, then once per optional param, then once per member of a Union param. It builds the values from the param name and type, and the mock transport records the request each call sends. Nothing reaches ElevenLabs and no API key is needed.
4. It matches methods by dotted path. A method that disappears and one that appears with the same HTTP method and path template count as a move.
5. It writes the report in this order: wire behavior changed, breaking, moved, type changed, added, skipped.

To run it on pull requests, use the composite action. It takes `from` and `to`, and an optional `guide`. It puts the report in the job summary and posts or updates one PR comment.

```yaml
- uses: sivaratrisrinivas/whatchanged@main
  with:
    from: 2.54.0
    to: 2.59.0
```

`examples/whatchanged.yml` shows a full workflow that reads both versions from `requirements.txt`.

The tool covers the sync client only. It skips websockets, and the argument values are synthesized, so a wire change that needs a specific combination of arguments can slip past it.
