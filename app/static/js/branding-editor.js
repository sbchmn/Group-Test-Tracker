(() => {
    document.querySelectorAll('[data-color-target]').forEach(picker => {
        const field = document.getElementById(picker.dataset.colorTarget);
        picker.addEventListener('input', () => {
            field.value = picker.value;
            field.dispatchEvent(new Event('input', {bubbles: true}));
        });
        field.addEventListener('input', () => {
            if (/^#[0-9a-f]{6}$/i.test(field.value)) picker.value = field.value;
        });
    });
    const editor = document.querySelector('[data-branding-form]');
    if (editor) {
        let unsaved = false;
        const markUnsaved = () => {
            unsaved = true;
            editor.querySelector('button[value="publish"]').disabled = true;
            document.getElementById('branding-save-status').textContent = 'You have unsaved changes. Save your draft before previewing or publishing them.';
        };
        editor.addEventListener('input', markUnsaved);
        editor.addEventListener('change', markUnsaved);
        editor.addEventListener('submit', () => { unsaved = false; });
        window.addEventListener('beforeunload', event => {
            if (unsaved) {
                event.preventDefault();
                event.returnValue = '';
            }
        });
    }
    const frame = document.getElementById('branding-preview');
    if (!frame) return;
    const surface = document.getElementById('preview-surface');
    const width = document.getElementById('preview-width');
    const theme = document.getElementById('preview-theme');
    const update = () => {
        frame.width = width.value;
        frame.src = '/admin/branding/preview/' + encodeURIComponent(surface.value) + '?theme=' + encodeURIComponent(theme.value);
    };
    [surface, width, theme].forEach(control => control.addEventListener('change', update));
})();
