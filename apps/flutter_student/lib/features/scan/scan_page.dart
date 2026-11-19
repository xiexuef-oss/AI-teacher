import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';
import 'package:tutor_contracts/tutor_contracts.dart';

import '../../core/providers.dart';
import 'scan_actions.dart';
import 'scan_command_store.dart';
import 'scan_preview.dart';
import 'scan_image.dart';

final scanImagePickerProvider = Provider<ImagePicker>((ref) => ImagePicker());

class ScanPage extends ConsumerStatefulWidget {
  const ScanPage({super.key});
  @override
  ConsumerState<ScanPage> createState() => _ScanPageState();
}

class _ScanPageState extends ConsumerState<ScanPage> {
  final stem = TextEditingController();
  final expressions = TextEditingController();
  final preview = ScanPreview();
  AuthSession? owner;
  int serial = 0;
  int pickerLease = 0;
  int loadLease = 0;
  bool busy = true;
  bool ready = false;
  bool writeFailed = false;
  String mime = 'image/jpeg';
  String message = '';
  String? questionId;
  ScanWorkspace? get workspace =>
      ref.read(scanActionsProvider.notifier).workspace;
  bool same(AuthSession auth, String id, int lease) =>
      mounted &&
      pickerLease == lease &&
      ref.read(authProvider).asData?.value.userId == auth.userId &&
      ref.read(authProvider).asData?.value.token == auth.token &&
      ref.read(authProvider).asData?.value.role == LocalRole.student &&
      workspace?.id == id;
  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final ticket = ++loadLease;
    ++pickerLease;
    try {
      final auth = await ref.read(authProvider.future);
      if (auth.role != LocalRole.student) {
        throw const WrongSession(LocalRole.student);
      }
      final bundle = await ref.read(scanActionsProvider.future);
      if (!mounted ||
          ticket != loadLease ||
          ref.read(authProvider).asData?.value.token != auth.token) {
        return;
      }
      owner = auth;
      final w = bundle!.workspace(bundle.activeWorkspaceId!);
      stem.text = w.stem;
      expressions.text = w.expressions;
      setState(() {
        ready = true;
        busy = false;
        questionId = w.confirmation?['question_id'] as String?;
        message = '原图不写入本机草稿，重新选择同图才能恢复内容上传。';
      });
      if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
        // System picker recovery is not proof of ownership of the lost selection.
        final lost = await ref
            .read(scanImagePickerProvider)
            .retrieveLostData()
            .catchError((Object _) => LostDataResponse.empty());
        if (mounted &&
            ticket == loadLease &&
            (lost.files?.isNotEmpty ?? false)) {
          setState(() => message = '发现系统临时选图，请重新选择原图验证；文字仍保留。');
        }
      }
    } catch (error) {
      if (mounted && ticket == loadLease) {
        setState(() {
          busy = false;
          message = '本机恢复失败，原始内容保留，请勿覆盖：$error';
        });
      }
    }
  }

  Future<void> _persist() async {
    final current = serial;
    try {
      await ref
          .read(scanActionsProvider.notifier)
          .edit(stem.text, expressions.text);
      if (current == serial) writeFailed = false;
    } catch (error) {
      if (mounted && current == serial) {
        setState(() {
          writeFailed = true;
          message = '本机保存失败，请勿退出；输入仍保留：$error';
        });
      }
      rethrow;
    }
  }

  void _edit() {
    serial++;
    questionId = null;
    _persist().catchError((Object _) {});
    setState(() {});
  }

  Future<void> _accept(
    XFile file,
    AuthSession auth,
    String id,
    int lease,
  ) async {
    void check() {
      if (!same(auth, id, lease)) throw StateError('旧选图已失效，请在当前身份重新选择');
    }

    check();
    final length = await file.length();
    check();
    if (length > 5 * 1024 * 1024) throw StateError('图片请小于5MB');
    final bytes = await file.readAsBytes();
    check();
    if (bytes.length > 5 * 1024 * 1024) throw StateError('图片请小于5MB');
    final info = inspectScanImage(bytes);
    final codec = await ui.instantiateImageCodec(bytes);
    try {
      check();
      if (codec.frameCount != 1) throw StateError('请选择静态图片');
      final frame = await codec.getNextFrame();
      frame.image.dispose();
      check();
    } finally {
      codec.dispose();
    }
    if (!ref.read(scanActionsProvider.notifier).sameImage(bytes)) {
      throw StateError('这张图片不同于原请求。请先明确开始新图片，旧记录会保留。');
    }
    check();
    preview.replace(bytes);
    mime = info.mime;
    serial++;
    questionId = null;
    final hasUploadHistory =
        workspace!.mediaId != null ||
        workspace!.commands.any(
          (command) => command.kind == 'upload' || command.kind == 'content',
        );
    setState(
      () => message = hasUploadHistory
          ? '原图已重新选择，历史请求可能已上传，请恢复原操作；原图不写入草稿。'
          : '本次尚未发起上传，原图不写入草稿；请遮盖姓名、学校等个人信息。',
    );
  }

  Future<void> _pick(ImageSource source) async {
    final auth = owner!;
    final id = workspace!.id;
    final lease = ++pickerLease;
    setState(() => busy = true);
    try {
      final file = await ref
          .read(scanImagePickerProvider)
          .pickImage(source: source, requestFullMetadata: false);
      if (file != null && same(auth, id, lease)) {
        await _accept(file, auth, id, lease);
      }
    } catch (error) {
      if (same(auth, id, lease)) setState(() => message = '无法选图或相机不可用：$error');
    } finally {
      if (same(auth, id, lease)) setState(() => busy = false);
    }
  }

  Future<void> _newWorkspace() async {
    final auth = owner!;
    final id = workspace!.id;
    final lease = pickerLease;
    final current = serial;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('开始新图片并保留旧记录？'),
        content: const Text('旧请求可能已完成或稍后完成。新图片不会取消旧请求，旧文字及未知记录仍保留。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('返回'),
          ),
          FilledButton(
            key: const ValueKey('scan.new.confirm'),
            onPressed: () => Navigator.pop(context, true),
            child: const Text('保留旧记录，开始新图片'),
          ),
        ],
      ),
    );
    if (confirmed != true || !same(auth, id, lease) || current != serial) {
      return;
    }
    try {
      await _persist();
      if (!same(auth, id, lease) || serial != current) return;
      setState(() => ready = false);
      await ref.read(scanActionsProvider.notifier).newWorkspace();
      if (!mounted || owner?.token != auth.token) return;
      ++pickerLease;
      ++serial;
      preview.clear();
      stem.clear();
      expressions.clear();
      questionId = null;
      writeFailed = false;
      setState(() {
        ready = true;
        busy = false;
        message = '已开始新图片；旧操作记录与文字仍保留。';
      });
    } catch (error) {
      if (mounted && owner?.token == auth.token) {
        setState(() {
          ready = true;
          message = '未切换图片，原输入仍保留：$error';
        });
      }
    }
  }

  Future<void> _run(String action) async {
    final auth = owner!;
    final id = workspace!.id;
    final lease = pickerLease;
    final current = serial;
    setState(() => busy = true);
    try {
      final actions = ref.read(scanActionsProvider.notifier);
      if (action == 'confirm') {
        await _persist();
        if (!same(auth, id, lease) || current != serial) return;
        await actions.confirm();
      } else if (action == 'retry') {
        await actions.retry(bytes: preview.bytes);
      } else if (action == 'ack') {
        await actions.acknowledge();
      } else if (action == 'observe') {
        await actions.observe();
      } else {
        await actions.upload(mime, preview.bytes);
      }
      if (!same(auth, id, lease)) return;
      setState(() {
        if (current == serial && !writeFailed) {
          questionId = workspace?.confirmation?['question_id'] as String?;
        }
        if (writeFailed) return;
        message = action == 'observe'
            ? '已查看当前扫描，仅作观察，不代表旧请求已确认。'
            : questionId != null
            ? '已匹配已有题目，请点击开始练习。'
            : '操作回执已记录。未实际识别图片，请手工填写题干；未匹配唯一题目时不会创建练习。';
      });
    } catch (error) {
      if (same(auth, id, lease)) {
        setState(
          () => message = error is ApiException && error.statusCode == 404
              ? '资源已到期或不可用，旧请求结果仍未知。文字及原请求保留，请明确开始新图片。'
              : error is ApiException && error.statusCode == 501
              ? '服务未启用（501）。文字与原操作保留，可稍后重试。'
              : '操作未确认，输入保留：$error',
        );
      }
    } finally {
      if (same(auth, id, lease)) setState(() => busy = false);
    }
  }

  @override
  void dispose() {
    ++pickerLease;
    ++loadLease;
    preview.clear();
    stem.dispose();
    expressions.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    ref.listen(authProvider, (previous, next) {
      if (previous?.asData?.value.token != next.asData?.value.token &&
          owner != null) {
        owner = null;
        ready = false;
        preview.clear();
        questionId = null;
        ++serial;
        Future.microtask(() {
          if (mounted) _load();
        });
      }
    });
    final bundle = ref.watch(scanActionsProvider).asData?.value;
    final w = bundle?.activeWorkspaceId == null
        ? null
        : bundle!.workspace(bundle.activeWorkspaceId!);
    final command = w?.active;
    final canResumeCreate =
        w?.mediaId != null &&
        w?.scanId == null &&
        w!.commands.any(
          (command) => command.kind == 'content' && command.phase == 'acked',
        );
    return Scaffold(
      key: const ValueKey('scan.page'),
      appBar: AppBar(title: const Text('拍题原型')),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          const Text('本地手工确认原型，未实际 OCR。上传不会自动开始练习。'),
          const Text(
            '仅支持PNG/JPEG，最大5MB、1200万像素。原图不写入草稿存储；选图组件和系统可能保留临时缓存，离页不代表缓存已删除。',
          ),
          if (!ready) const LinearProgressIndicator(),
          Text(message),
          if (preview.bytes != null)
            SizedBox(
              height: 180,
              child: Image(image: preview.provider!, fit: BoxFit.contain),
            ),
          Wrap(
            spacing: 12,
            children: [
              OutlinedButton(
                key: const ValueKey('scan.pick'),
                onPressed: !ready || busy
                    ? null
                    : () => _pick(ImageSource.gallery),
                child: const Text('选择图片'),
              ),
              OutlinedButton(
                onPressed: !ready || busy
                    ? null
                    : () => _pick(ImageSource.camera),
                child: const Text('拍照（不可用时请选择图片）'),
              ),
              OutlinedButton(
                key: const ValueKey('scan.new'),
                onPressed: !ready ? null : _newWorkspace,
                child: const Text('开始新图片并保留旧记录'),
              ),
            ],
          ),
          TextField(
            key: const ValueKey('scan.stem'),
            controller: stem,
            onChanged: (_) => _edit(),
            enabled: ready,
            maxLines: 5,
            maxLength: 4000,
            decoration: const InputDecoration(labelText: '手工填写题干'),
          ),
          TextField(
            key: const ValueKey('scan.expressions'),
            controller: expressions,
            onChanged: (_) => _edit(),
            enabled: ready,
            maxLines: 2,
            maxLength: 4000,
            decoration: const InputDecoration(labelText: '手工补充表达式（LaTeX，可选）'),
          ),
          if (command != null) ...[
            Text(
              command.phase == 'result_known'
                  ? '已收到原操作的成功回执，可以仅在本机确认，无需图片或联网。'
                  : command.phase == 'unavailable'
                  ? '原资源已不可用，无法据此判断原请求是否成功。可以明确开始新图片，保留旧未知记录。'
                  : '有尚未确认的原操作，重试始终使用原请求。新编辑会单独保留。',
            ),
            if (command.phase == 'result_known')
              OutlinedButton(
                key: const ValueKey('scan.ack'),
                onPressed: busy ? null : () => _run('ack'),
                child: const Text('本机确认历史结果'),
              )
            else
              OutlinedButton(
                key: const ValueKey('scan.retry'),
                onPressed: busy ? null : () => _run('retry'),
                child: const Text('重试原操作'),
              ),
          ],
          FilledButton(
            key: const ValueKey('scan.upload'),
            onPressed:
                !ready ||
                    busy ||
                    command != null ||
                    (preview.bytes == null && !canResumeCreate)
                ? null
                : () => _run('upload'),
            child: Text(canResumeCreate ? '继续建立扫描' : '上传临时图片'),
          ),
          if (w?.scanId != null || w?.legacyScanId != null)
            OutlinedButton(
              key: const ValueKey('scan.observe'),
              onPressed: busy ? null : () => _run('observe'),
              child: const Text('检查扫描状态'),
            ),
          FilledButton(
            key: const ValueKey('scan.confirm'),
            onPressed:
                !ready ||
                    busy ||
                    command != null ||
                    stem.text.trim().isEmpty ||
                    (w?.scanId == null && w?.observation == null)
                ? null
                : () => _run('confirm'),
            child: const Text('确认题干并匹配已有题目'),
          ),
          if (questionId != null)
            FilledButton(
              key: const ValueKey('scan.start'),
              onPressed: () => context.go(
                '/questions/${Uri.encodeComponent(questionId!)}/solve',
              ),
              child: const Text('开始练习'),
            ),
          TextButton(
            key: const ValueKey('scan.practice'),
            onPressed: () => context.go('/practice'),
            child: const Text('去练习'),
          ),
        ],
      ),
    );
  }
}
