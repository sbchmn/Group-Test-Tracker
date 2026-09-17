import io
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from pypdf import PdfWriter

from app import create_app, db
from app.models import (
    GroupTest, NotificationConfig, PublicResult, ResultAnalysisRun, Tag, User,
)
from app.result_analysis.service import AnalysisConflict, apply_analysis_run, enqueue_analysis, persist_extraction
from app.result_analysis.jobs import process_next_run, process_run
from app.result_analysis.diagnostics import append_provider_diagnostic, read_provider_diagnostics
from app.result_analysis.providers.base import classify_sdk_error
from app.result_analysis.sources import SourceError, _safe_public_url, prepare_document
from app.result_analysis.taxonomy import canonical_types_for_row, canonicalize_label
from app.result_analysis.types import (
    SCHEMA_VERSION, AnalysisDocument, AnalysisExtraction, ProviderCapabilities, validate_extraction,
)
from app.telegram_result_review import handle_review_callback, handle_review_reply, notify_review_ready


def extraction_payload(findings=None):
    return {
        'compound': 'Tirzepatide',
        'metadata': {
            'laboratory': 'Example Analytical',
            'batch_lot': 'LOT-7',
            'report_date': '2026-09-01',
            'sample_id': 'SAMPLE-2',
            'methods': ['HPLC', 'LC-MS'],
        },
        'findings': findings or [],
        'warnings': [],
    }


def finding(label, canonical, value, aggregate=False, confidence=0.98):
    return {
        'source_label': label,
        'canonical_type': canonical,
        'reported_value': value,
        'evidence': f'{label}: {value}',
        'page_number': 1,
        'confidence': confidence,
        'is_reported_aggregate': aggregate,
        'vial_identifier': None,
    }


class ResultAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / 'test.db'
        self.diagnostic_log_path = Path(self.temp_dir.name) / 'result-analysis-diagnostics.log'
        self.app = create_app({
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
            'WTF_CSRF_ENABLED': False,
            'RESULT_ANALYSIS_DIAGNOSTIC_LOG_PATH': str(self.diagnostic_log_path),
            'RESULT_ANALYSIS_DIAGNOSTIC_LOG_MAX_BYTES': 4096,
        })
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.user = User(username='analysis-admin', email='analysis@example.com', is_admin=True)
        self.user.set_password('secret-pass')
        db.session.add(self.user)
        db.session.add_all([
            NotificationConfig(key='result_analysis_openai_enabled', value='true'),
            NotificationConfig(key='result_analysis_openai_api_key', value='test-key'),
            NotificationConfig(key='result_analysis_openai_model', value='test-model'),
            NotificationConfig(key='storage_allowed_formats', value='JPEG,PNG,WEBP,GIF,PDF'),
            NotificationConfig(key='storage_max_upload_size_mb', value='20'),
        ])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()
        self.temp_dir.cleanup()

    def _group_test(self):
        test = GroupTest(
            title='Tirzepatide Test', compound='Tirzepatide', status='closed', created_by=self.user.id,
            results_image_key='result-images/group-tests/report.pdf',
            lab_test_details=[
                {'name': 'MASS, PURITY + ID', 'price': 360, 'vials_needed': 1},
                {'name': 'STERILITY', 'price': 290, 'vials_needed': 0, 'result': 'Pass'},
            ],
        )
        db.session.add(test)
        db.session.commit()
        return test

    def test_taxonomy_recognizes_composite_rows_and_aliases(self):
        self.assertEqual(canonicalize_label('LAL endotoxin'), 'Endotoxin')
        self.assertEqual(canonical_types_for_row('MASS, PURITY + ID'), ['Identity', 'Purity', 'Mass'])
        self.assertIsNone(canonicalize_label('Unknown custom panel'))

    def test_taxonomy_recognizes_common_coa_labels_contextually(self):
        self.assertEqual(canonicalize_label('FTIR Identification and Composition Analysis'), 'Identity')
        self.assertEqual(canonicalize_label('HPLC Purity of Peptide Assay'), 'Purity')
        self.assertEqual(canonicalize_label('HPLC Potency Assay'), 'Net Content')
        self.assertEqual(canonical_types_for_row('HPLC Potency Assay'), ['Net Content'])
        self.assertEqual(canonicalize_label('Bacterial Endotoxins Test (USP <85>)'), 'Endotoxin')
        self.assertIsNone(canonicalize_label('Peptide-to-Excipients Ratio'))

    def test_extraction_validation_rejects_extra_fields_and_bounds_confidence(self):
        payload = extraction_payload([finding('Purity', 'Purity', '99.4%')])
        self.assertEqual(validate_extraction(payload)['findings'][0]['reported_value'], '99.4%')
        invalid = extraction_payload([finding('Purity', 'Purity', '99.4%', confidence=2)])
        with self.assertRaises(ValueError):
            validate_extraction(invalid)
        payload['unexpected'] = True
        with self.assertRaises(ValueError):
            validate_extraction(payload)

    def test_queue_is_idempotent_and_automatic_queue_honors_global_flag(self):
        test = self._group_test()
        self.assertIsNone(enqueue_analysis(test, 'upload', self.user.id, automatic=True))
        first = enqueue_analysis(test, 'upload', self.user.id, provider='openai')
        second = enqueue_analysis(test, 'upload', self.user.id, provider='openai')
        self.assertEqual(first.id, second.id)
        self.assertEqual(ResultAnalysisRun.query.count(), 1)

    def test_group_test_review_fills_blank_composite_and_never_overwrites(self):
        test = self._group_test()
        run = ResultAnalysisRun(
            group_test_id=test.id, source_kind='upload', source_reference=test.results_image_key,
            provider='openai', provider_model='test-model', status='analyzing', max_attempts=3,
        )
        db.session.add(run)
        db.session.flush()
        payload = extraction_payload([
            finding('Identity by LC-MS', 'Identity', 'Confirmed'),
            finding('Purity by HPLC', 'Purity', '99.4%'),
            finding('Net Mass', 'Mass', '10.2 mg', aggregate=True),
            finding('Sterility', 'Sterility', 'No growth'),
        ])
        persist_extraction(run, AnalysisExtraction(payload, 'test-model'))
        db.session.commit()
        fill = next(item for item in run.findings if item.proposed_action == 'fill')
        conflict = next(item for item in run.findings if item.proposed_action == 'conflict')
        self.assertEqual(fill.reported_value, 'Identity: Confirmed; Purity: 99.4%; Mass: 10.2 mg')
        count = apply_analysis_run(
            run,
            {
                fill.id: {'accepted': True, 'value': fill.reported_value},
                conflict.id: {'accepted': True, 'value': 'Must not replace'},
            },
            self.user.id,
            include_metadata=True,
        )
        self.assertEqual(count, 1)
        self.assertEqual(test.lab_test_details[0]['result'], fill.reported_value)
        self.assertEqual(test.lab_test_details[1]['result'], 'Pass')
        self.assertIn('<!-- result-analysis:start -->', test.description)

    def test_group_test_can_create_unmatched_canonical_row_but_not_unknown(self):
        test = self._group_test()
        run = ResultAnalysisRun(
            group_test_id=test.id, source_kind='upload', source_reference=test.results_image_key,
            provider='openai', provider_model='test-model', status='analyzing', max_attempts=3,
        )
        db.session.add(run)
        db.session.flush()
        payload = extraction_payload([
            finding('Endotoxin (USP <85>)', 'Endotoxin', '1.158 EU/mL'),
            finding('Fentanyl Screen', 'Unknown', 'Not Detected'),
        ])
        persist_extraction(run, AnalysisExtraction(payload, 'test-model'))
        db.session.commit()

        create = next(item for item in run.findings if item.canonical_type == 'Endotoxin')
        unknown = next(item for item in run.findings if item.canonical_type is None)
        self.assertEqual(create.proposed_action, 'create')
        self.assertEqual(unknown.proposed_action, 'unrecognized')

        count = apply_analysis_run(
            run,
            {
                create.id: {'accepted': True},
                unknown.id: {'accepted': True},
            },
            self.user.id,
        )

        self.assertEqual(count, 1)
        self.assertEqual(test.lab_test_details[-1], {
            'name': 'Endotoxin',
            'price': 0.0,
            'vials_needed': 0,
            'result': '1.158 EU/mL',
        })
        self.assertEqual(unknown.review_decision, 'rejected')

    def test_group_test_create_is_unchecked_and_rechecks_for_duplicate_rows(self):
        test = self._group_test()
        run = ResultAnalysisRun(
            group_test_id=test.id, source_kind='upload', source_reference=test.results_image_key,
            provider='openai', provider_model='test-model', status='analyzing', max_attempts=3,
        )
        db.session.add(run)
        db.session.flush()
        persist_extraction(run, AnalysisExtraction(
            extraction_payload([finding('Appearance', 'Appearance', 'Good')]),
            'test-model',
        ))
        db.session.commit()
        create = next(iter(run.findings))

        client = self.app.test_client()
        client.post('/login', data={'username': self.user.username, 'password': 'secret-pass'})
        response = client.get(f'/admin/result-analysis/{run.id}')
        html = response.get_data(as_text=True)
        checkbox = f'name="accept_{create.id}" value="yes"'
        self.assertIn(checkbox, html)
        self.assertNotIn(f'{checkbox} checked', html)

        test.lab_test_details = [
            *test.lab_test_details,
            {'name': 'Appearance', 'price': 25.0, 'vials_needed': 0},
        ]
        db.session.commit()
        with self.assertRaises(AnalysisConflict):
            apply_analysis_run(run, {create.id: {'accepted': True}}, self.user.id)

    def test_public_result_adds_only_new_canonical_rows(self):
        result = PublicResult(
            title='Public Tirzepatide', summary='Manual note', results_link='https://example.com/report.pdf',
            item_results=[{'name': 'Purity', 'result': '99.0%'}], created_by=self.user.id,
        )
        db.session.add(result)
        db.session.flush()
        run = ResultAnalysisRun(
            public_result_id=result.id, source_kind='link', source_reference=result.results_link,
            provider='openai', provider_model='test-model', status='analyzing', max_attempts=3,
        )
        db.session.add(run)
        db.session.flush()
        payload = extraction_payload([
            finding('HPLC Purity', 'Purity', '99.4%'),
            finding('Peptide Mass', 'Mass', '10.2 mg'),
        ])
        persist_extraction(run, AnalysisExtraction(payload, 'test-model'))
        db.session.commit()
        create = next(item for item in run.findings if item.proposed_action == 'create')
        conflict = next(item for item in run.findings if item.proposed_action == 'conflict')
        apply_analysis_run(
            run,
            {create.id: {'accepted': True}, conflict.id: {'accepted': True}},
            self.user.id,
            include_metadata=True,
        )
        self.assertEqual(result.item_results, [
            {'name': 'Purity', 'result': '99.0%'},
            {'name': 'Mass', 'result': '10.2 mg'},
        ])
        self.assertIn('Manual note', result.summary)
        self.assertIn('Analysis metadata:', result.summary)

    @patch('app.telegram_result_review.edit_telegram_message', return_value=True)
    @patch('app.telegram_result_review.delete_telegram_message', return_value=True)
    @patch('app.telegram_result_review.send_telegram_interactive_message')
    def test_telegram_public_result_review_names_edits_and_publishes_in_thread(
            self, send_message, delete_message, edit_message):
        result = PublicResult(
            title='Pending COA review', results_link='https://example.com/coa.pdf', item_results=[],
            created_by=self.user.id, publication_status='needs_review', submission_platform='telegram',
            submission_chat_id='-10042', submission_thread_id='7', submission_message_id='10',
            review_state_json={'selected': {}, 'messages': [], 'submission_messages': ['11']},
        )
        db.session.add(result)
        db.session.flush()
        run = ResultAnalysisRun(
            public_result_id=result.id, source_kind='link', source_reference=result.results_link,
            provider='openai', provider_model='test-model', status='analyzing', max_attempts=3,
        )
        db.session.add(run)
        db.session.flush()
        persist_extraction(run, AnalysisExtraction(
            extraction_payload([finding('HPLC Potency Assay', 'Net Content', '67.9 mg')]),
            'test-model',
        ))
        db.session.commit()
        send_message.side_effect = ['20', '21', '22']
        self.assertTrue(notify_review_ready(run))

        ok, notice = handle_review_callback(self.user, '-10042', 7, f'ra:a:{run.id}')
        self.assertFalse(ok)
        self.assertEqual(notice, 'Set the Result name before publishing.')
        ok, _ = handle_review_callback(self.user, '-10042', 7, f'ra:n:{run.id}')
        self.assertTrue(ok)
        self.assertTrue(handle_review_reply(self.user, '-10042', 7, {
            'message_id': 30, 'text': 'Tirzepatide BT Labs',
            'reply_to_message': {'message_id': 21},
        }))
        finding_row = run.findings[0]
        ok, _ = handle_review_callback(self.user, '-10042', 7, f'ra:t:{run.id}:{finding_row.id}')
        self.assertTrue(ok)
        ok, _ = handle_review_callback(self.user, '-10042', 7, f'ra:a:{run.id}')
        self.assertTrue(ok)

        self.assertEqual(result.publication_status, 'published')
        self.assertEqual(result.title, 'Tirzepatide BT Labs')
        self.assertEqual(result.item_results, [{'name': 'Net Content', 'result': '67.9 mg'}])
        deleted = {(str(call.args[0]), str(call.args[1])) for call in delete_message.call_args_list}
        self.assertIn(('-10042', '10'), deleted)
        self.assertIn(('-10042', '11'), deleted)
        self.assertTrue(edit_message.called)

    def test_public_result_detail_includes_back_link_and_attached_pdf(self):
        result = PublicResult(
            title='Published COA', results_link='https://example.com/coa.pdf',
            results_image_key='result-images/public-results/report.pdf', item_results=[],
            created_by=self.user.id, publication_status='published',
        )
        db.session.add(result)
        db.session.commit()
        client = self.app.test_client()
        client.post('/login', data={'username': self.user.username, 'password': 'secret-pass'})
        response = client.get(f'/public-results/{result.id}')
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Back to My Results', body)
        self.assertIn('iframe', body)
        self.assertIn(f'/result-image/public/{result.id}', body)

    @patch('app.telegram_result_review.edit_telegram_message', return_value=True)
    def test_telegram_review_tags_use_paginated_save_workflow(self, edit_message):
        tags = [Tag(name=f'Tag {index:02d}', normalized_name=f'tag-{index:02d}') for index in range(12)]
        db.session.add_all(tags)
        result = PublicResult(
            title='Pending COA review', results_link='https://example.com/coa.pdf', item_results=[],
            created_by=self.user.id, publication_status='needs_review', submission_platform='telegram',
            submission_chat_id='-10042', review_state_json={'selected': {}, 'messages': []},
        )
        db.session.add(result)
        db.session.flush()
        run = ResultAnalysisRun(
            public_result_id=result.id, source_kind='link', source_reference=result.results_link,
            provider='openai', provider_model='test-model', status='needs_review', max_attempts=3,
        )
        db.session.add(run)
        db.session.flush()
        db.session.commit()

        ok, _ = handle_review_callback(self.user, '-10042', None, f'ra:tags:{run.id}:0')
        self.assertTrue(ok)
        tag_page = edit_message.call_args.args[3]
        tag_buttons = [button for row in tag_page['inline_keyboard'] for button in row if button['callback_data'].startswith(f'ra:tag:{run.id}:')]
        self.assertEqual(len(tag_buttons), 10)

        first_tag_id = tags[0].id
        ok, _ = handle_review_callback(self.user, '-10042', None, f'ra:tag:{run.id}:0:{first_tag_id}')
        self.assertTrue(ok)
        self.assertIn(first_tag_id, result.review_state_json['draft_tag_ids'])
        self.assertNotIn('tag_ids', result.review_state_json)

        ok, _ = handle_review_callback(self.user, '-10042', None, f'ra:tagsave:{run.id}')
        self.assertTrue(ok)
        self.assertEqual(result.review_state_json['tag_ids'], [first_tag_id])

    @patch('app.telegram_result_review.delete_result_image', return_value=True)
    @patch('app.telegram_result_review.upload_result_image', return_value='result-images/public-results/added.pdf')
    @patch('app.telegram_result_review.download_telegram_photo')
    @patch('app.telegram_result_review.edit_telegram_message', return_value=True)
    @patch('app.telegram_result_review.send_telegram_interactive_message')
    def test_telegram_review_can_add_complementary_link_and_file(
            self, send_message, edit_message, download_photo, upload_image, delete_image):
        result = PublicResult(
            title='Pending COA review', results_link='https://example.com/original.pdf', item_results=[],
            created_by=self.user.id, publication_status='needs_review', submission_platform='telegram',
            submission_chat_id='-10042', review_message_id='20',
            review_state_json={'title': 'Named COA', 'selected': {}, 'messages': []},
        )
        db.session.add(result)
        db.session.flush()
        run = ResultAnalysisRun(
            public_result_id=result.id, source_kind='link', source_reference=result.results_link,
            provider='openai', provider_model='test-model', status='needs_review', max_attempts=3,
        )
        db.session.add(run)
        db.session.flush()
        persist_extraction(run, AnalysisExtraction(
            extraction_payload([finding('Purity', 'Purity', '99.4%')]), 'test-model',
        ))
        db.session.commit()
        send_message.side_effect = ['30', '31']
        download_photo.return_value = io.BytesIO(b'pdf-bytes')
        download_photo.return_value.filename = 'added.pdf'

        ok, _ = handle_review_callback(self.user, '-10042', None, f'ra:source:{run.id}')
        self.assertTrue(ok)
        ok, _ = handle_review_callback(self.user, '-10042', None, f'ra:link:{run.id}')
        self.assertTrue(ok)
        self.assertTrue(handle_review_reply(self.user, '-10042', None, {
            'message_id': 40, 'text': 'https://example.com/new-report.pdf',
            'reply_to_message': {'message_id': 30},
        }))
        ok, _ = handle_review_callback(self.user, '-10042', None, f'ra:file:{run.id}')
        self.assertTrue(ok)
        self.assertTrue(handle_review_reply(self.user, '-10042', None, {
            'message_id': 41, 'document': {'file_id': 'file-1', 'file_name': 'added.pdf'},
            'reply_to_message': {'message_id': 31},
        }))
        self.assertEqual(result.review_state_json['draft_results_link'], 'https://example.com/new-report.pdf')
        self.assertEqual(result.review_state_json['draft_results_image_key'], 'result-images/public-results/added.pdf')

        ok, _ = handle_review_callback(self.user, '-10042', None, f'ra:sourcesave:{run.id}')
        self.assertTrue(ok)
        ok, _ = handle_review_callback(self.user, '-10042', None, f'ra:a:{run.id}')
        self.assertTrue(ok)
        self.assertEqual(result.results_link, 'https://example.com/new-report.pdf')
        self.assertEqual(result.results_image_key, 'result-images/public-results/added.pdf')
        self.assertEqual(result.publication_status, 'published')

    @patch('app.result_analysis.sources.socket.getaddrinfo')
    def test_link_validation_rejects_private_resolution(self, getaddrinfo):
        getaddrinfo.return_value = [(2, 1, 6, '', ('127.0.0.1', 443))]
        with self.assertRaises(SourceError):
            _safe_public_url('https://example.test/report.pdf')
        with self.assertRaises(SourceError):
            _safe_public_url('file:///etc/passwd')

    def test_gif_analysis_uses_first_frame_and_storage_allowlist(self):
        output = io.BytesIO()
        first = Image.new('RGB', (2, 2), 'red')
        second = Image.new('RGB', (2, 2), 'blue')
        first.save(output, format='GIF', save_all=True, append_images=[second])
        settings = {'max_document_mb': 20, 'max_pages': 25}
        document = prepare_document(output.getvalue(), 'image/gif', settings)
        self.assertEqual(document.content_type, 'image/png')
        self.assertTrue(document.raw_bytes.startswith(b'\x89PNG'))

    def test_pdf_analysis_accepts_recoverable_cross_reference_errors(self):
        output = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(output)
        recoverable_pdf = re.sub(br'startxref\n\d+', b'startxref\n0', output.getvalue())

        document = prepare_document(
            recoverable_pdf,
            'application/pdf',
            {'max_document_mb': 20, 'max_pages': 25},
        )

        self.assertEqual(document.content_type, 'application/pdf')
        self.assertEqual(document.raw_bytes, recoverable_pdf)

    @patch('pypdf.PdfReader', side_effect=ValueError('unsupported PDF structure'))
    def test_pdf_analysis_falls_back_to_page_renderer(self, _pdf_reader):
        output = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(output)

        document = prepare_document(
            output.getvalue(),
            'application/pdf',
            {'max_document_mb': 20, 'max_pages': 25},
        )

        self.assertEqual(document.content_type, 'application/pdf')

    def test_analysis_admin_routes_require_admin_and_preserve_masked_secret(self):
        member = User(username='analysis-member', email='member@example.com')
        member.set_password('secret-pass')
        db.session.add(member)
        db.session.commit()
        client = self.app.test_client()
        client.post('/login', data={'username': member.username, 'password': 'secret-pass'})
        response = client.get('/admin/settings/result-analysis', follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/dashboard', response.headers['Location'])

        client.get('/logout')
        client.post('/login', data={'username': self.user.username, 'password': 'secret-pass'})
        response = client.get('/admin/settings/result-analysis')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Result Analysis Settings', response.get_data(as_text=True))
        response = client.post('/admin/settings/result-analysis', data={
            'enabled': 'y',
            'active_provider': 'openai',
            'openai_enabled': 'y',
            'openai_api_key': '••••••••••••',
            'openai_model': 'test-model',
            'xai_api_key': '',
            'xai_model': 'grok-test',
            'anthropic_api_key': '',
            'anthropic_model': 'claude-test',
            'max_document_mb': '20',
            'max_pdf_pages': '25',
            'download_timeout_seconds': '20',
            'max_attempts': '3',
            'submit': 'Save Result Analysis Settings',
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        saved_key = NotificationConfig.query.filter_by(key='result_analysis_openai_api_key').first()
        self.assertEqual(saved_key.value, 'test-key')

    def test_provider_diagnostic_log_redacts_secrets_and_stays_bounded(self):
        class FakeBadRequest(Exception):
            status_code = 400
            request_id = 'req_diagnostic_123'
            body = {
                'error': {
                    'code': 'unsupported_parameter',
                    'param': 'max_output_tokens',
                    'message': 'Bad request using sk-proj-supersecret1234567890',
                },
            }

        error = classify_sdk_error(FakeBadRequest('Bearer another-secret-value'))
        append_provider_diagnostic('openai', 'connection_test', 'gpt-test', 'failed', exception=error)
        contents = read_provider_diagnostics()
        entry = json.loads(contents.strip())
        self.assertEqual(entry['status_code'], 400)
        self.assertEqual(entry['error_code'], 'unsupported_parameter')
        self.assertEqual(entry['error_param'], 'max_output_tokens')
        self.assertEqual(entry['request_id'], 'req_diagnostic_123')
        self.assertIn('[REDACTED]', entry['detail'])
        self.assertNotIn('supersecret', contents)

        for index in range(100):
            append_provider_diagnostic(
                'openai', 'connection_test', 'gpt-test', 'failed',
                exception=ValueError(f'bounded-entry-{index}-' + ('x' * 500)),
            )
        self.assertLessEqual(self.diagnostic_log_path.stat().st_size, 4096)
        self.assertIn('bounded-entry-99', read_provider_diagnostics())

    @patch('app.routes.build_provider')
    def test_connection_failure_diagnostic_is_admin_visible(self, build_provider):
        class FakeNotFound(Exception):
            status_code = 404
            request_id = 'req_visible_456'
            body = {
                'error': {
                    'code': 'model_not_found',
                    'message': 'Model is unavailable. <script>alert(1)</script>',
                },
            }

        build_provider.return_value.test_connection.side_effect = classify_sdk_error(FakeNotFound())
        client = self.app.test_client()
        client.post('/login', data={'username': self.user.username, 'password': 'secret-pass'})
        response = client.post('/admin/settings/result-analysis/test/openai', follow_redirects=True)
        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Recent Provider Diagnostics', page)
        self.assertIn('req_visible_456', page)
        self.assertIn('model_not_found', page)
        self.assertIn('Model is unavailable.', page)
        self.assertNotIn('<script>alert(1)</script>', page)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', page)

    def test_admin_can_queue_link_and_open_review_without_provider_call(self):
        result = PublicResult(
            title='Queued Result', results_link='https://example.com/report.pdf',
            item_results=[], created_by=self.user.id,
        )
        db.session.add(result)
        db.session.commit()
        client = self.app.test_client()
        client.post('/login', data={'username': self.user.username, 'password': 'secret-pass'})
        response = client.post(
            f'/admin/result-analysis/public-result/{result.id}/queue/link',
            data={'provider': 'openai'},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        run = ResultAnalysisRun.query.filter_by(public_result_id=result.id).one()
        self.assertEqual(run.status, 'queued')
        self.assertTrue(run.bypass_duplicate_check)
        review = client.get(f'/admin/result-analysis/{run.id}')
        self.assertEqual(review.status_code, 200)
        self.assertIn(f'Run {run.id}', review.get_data(as_text=True))

    def test_action_queue_surfaces_analysis_reviews_and_failures(self):
        group_test = self._group_test()
        public_result = PublicResult(
            title='Failed Public Analysis',
            results_link='https://example.com/failed-report.pdf',
            item_results=[],
            created_by=self.user.id,
        )
        hidden_result = PublicResult(
            title='Already Applied Analysis',
            results_link='https://example.com/applied-report.pdf',
            item_results=[],
            created_by=self.user.id,
        )
        db.session.add_all([public_result, hidden_result])
        db.session.flush()
        review_run = ResultAnalysisRun(
            group_test_id=group_test.id, source_kind='upload', source_reference=group_test.results_image_key,
            provider='openai', provider_model='review-model', status='analyzing', max_attempts=3,
        )
        failed_run = ResultAnalysisRun(
            public_result_id=public_result.id, source_kind='link', source_reference=public_result.results_link,
            provider='openai', provider_model='failure-model', status='failed', max_attempts=3,
            error_code='provider_error', error_message='Provider requires administrator attention.',
        )
        applied_run = ResultAnalysisRun(
            public_result_id=hidden_result.id, source_kind='link', source_reference=hidden_result.results_link,
            provider='openai', provider_model='applied-model', status='applied', max_attempts=3,
        )
        db.session.add_all([review_run, failed_run, applied_run])
        db.session.flush()
        persist_extraction(
            review_run,
            AnalysisExtraction(extraction_payload([finding('Purity', 'Purity', '99.4%')]), 'review-model'),
        )
        db.session.commit()

        client = self.app.test_client()
        client.post('/login', data={'username': self.user.username, 'password': 'secret-pass'})
        response = client.get('/admin/action-queue?status=recruiting&q=no-participant-match')
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('Tirzepatide Test', page)
        self.assertIn('Review Findings', page)
        self.assertIn('Failed Public Analysis', page)
        self.assertIn('Provider requires administrator attention.', page)
        self.assertIn('Inspect Failure', page)
        self.assertIn('Acknowledge', page)
        self.assertNotIn('Already Applied Analysis', page)

        acknowledge = client.post(
            f'/admin/result-analysis/{failed_run.id}/acknowledge-failure',
            follow_redirects=True,
        )
        self.assertEqual(acknowledge.status_code, 200)
        self.assertNotIn('Failed Public Analysis', acknowledge.get_data(as_text=True))
        db.session.refresh(failed_run)
        self.assertEqual(failed_run.status, 'failed')
        self.assertEqual(failed_run.reviewed_by_id, self.user.id)
        self.assertIsNotNone(failed_run.reviewed_at)

    @patch('app.result_analysis.jobs.acquire_run_source')
    @patch('app.result_analysis.jobs.build_provider')
    def test_worker_claims_and_processes_run_with_mocked_provider(self, build_provider, acquire_source):
        test = self._group_test()
        run = enqueue_analysis(test, 'upload', self.user.id, provider='openai')
        document = AnalysisDocument('image/png', b'png-bytes', 'a' * 64)
        acquire_source.return_value = document

        provider = build_provider.return_value
        provider.capabilities = ProviderCapabilities(True, ('image/png',))
        provider.analyze.return_value = AnalysisExtraction(
            extraction_payload([finding('Purity', 'Purity', '99.4%')]),
            'mock-model',
            request_id='request-1',
            usage={'input_tokens': 10, 'output_tokens': 5},
        )
        processed = process_next_run()
        self.assertEqual(processed.id, run.id)
        self.assertEqual(processed.status, 'needs_review')
        self.assertEqual(processed.source_sha256, 'a' * 64)
        self.assertEqual(processed.usage_json['request_id'], 'request-1')
        self.assertEqual(len(processed.findings), 1)

    @patch('app.result_analysis.jobs.acquire_run_source')
    @patch('app.result_analysis.jobs.build_provider')
    def test_manual_run_bypasses_completed_source_duplicate(self, build_provider, acquire_source):
        test = self._group_test()
        prior = ResultAnalysisRun(
            group_test_id=test.id, source_kind='upload', source_reference=test.results_image_key,
            source_sha256='a' * 64, provider='openai', provider_model='test-model',
            schema_version=SCHEMA_VERSION, status='applied', max_attempts=3,
        )
        db.session.add(prior)
        db.session.commit()
        run = enqueue_analysis(
            test, 'upload', self.user.id, provider='openai', bypass_duplicate_check=True,
        )
        document = AnalysisDocument('image/png', b'png-bytes', 'a' * 64)
        acquire_source.return_value = document
        provider = build_provider.return_value
        provider.capabilities = ProviderCapabilities(True, ('image/png',))
        provider.analyze.return_value = AnalysisExtraction(
            extraction_payload([finding('Purity', 'Purity', '99.4%')]),
            'test-model',
        )

        process_run(run)

        self.assertEqual(run.status, 'needs_review')
        provider.analyze.assert_called_once()

    @patch('app.result_analysis.jobs.acquire_run_source')
    @patch('app.result_analysis.jobs.build_provider')
    def test_automatic_run_still_deduplicates_completed_source(self, build_provider, acquire_source):
        test = self._group_test()
        prior = ResultAnalysisRun(
            group_test_id=test.id, source_kind='upload', source_reference=test.results_image_key,
            source_sha256='a' * 64, provider='openai', provider_model='test-model',
            schema_version=SCHEMA_VERSION, status='applied', max_attempts=3,
        )
        db.session.add(prior)
        db.session.commit()
        run = enqueue_analysis(test, 'upload', self.user.id, provider='openai')
        acquire_source.return_value = AnalysisDocument('image/png', b'png-bytes', 'a' * 64)
        build_provider.return_value.capabilities = ProviderCapabilities(True, ('image/png',))

        process_run(run)

        self.assertEqual(run.status, 'superseded')
        self.assertEqual(run.error_code, 'duplicate_source')
        build_provider.return_value.analyze.assert_not_called()


if __name__ == '__main__':
    unittest.main()
