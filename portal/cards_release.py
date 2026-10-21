"""Remove only the classification-agreement card; retain API/export data."""
import c15_release as previous

portal = previous.portal
original_pages = previous.pages
replace = previous.replace


def pages():
    result = original_pages()
    html, mime = result['/compare/']
    card = '<div><div class="hint">Classification agreement · Successful pairs</div><div id="batch-agreement" class="batch-number">—</div><div id="batch-model-agreement" class="hint">Decision/model agreement is not yet available. Intended corpus difficulty is not a ground-truth label.</div></div>'
    html = replace(html, card + '\n', '')
    html = replace(html, '.batch-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));',
        '.batch-cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));')
    result['/compare/'] = html, mime
    js, mime = result['/compare/batch.js']
    js = replace(js, '"batch-ratio", "batch-agreement",', '"batch-ratio",')
    js = replace(js, '"batch-paired-distribution", "batch-model-agreement"', '"batch-paired-distribution"')
    lines = js.splitlines(keepends=True)
    removed = [line for line in lines if 'text("batch-agreement",' in line or 'text("batch-model-agreement",' in line]
    assert len(removed) == 2, 'Unexpected agreement render structure'
    js = ''.join(line for line in lines if line not in removed)
    assert 'batch-agreement' not in js and 'batch-model-agreement' not in js
    result['/compare/batch.js'] = js, mime
    return result


previous.english.pages = pages

if __name__ == '__main__':
    portal.main()