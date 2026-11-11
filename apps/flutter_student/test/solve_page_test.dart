import 'dart:convert';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_student/core/adaptive_split.dart';
import 'package:tutor_student/core/theme.dart';

import 'support/app_harness.dart';
import 'support/fake_backend.dart';

Finder key(String name) => find.byKey(ValueKey(name));

Future<void> open(
  WidgetTester tester,
  AppHarness h, {
  Size size = tabletLandscape,
  String origin = 'practice',
  String? reviewItemId,
  double textScale = 1,
  ThemeData? theme,
  String? questionId,
}) async {
  useSize(tester, size);
  await tester.pumpWidget(
    h.solvePage(
      origin: origin,
      reviewItemId: reviewItemId,
      textScale: textScale,
      theme: theme,
      questionId: questionId ?? '',
    ),
  );
  await settle(tester);
}

Future<void> choose(WidgetTester tester, String option) async {
  await tester.tap(key('option.$option'));
  await tester.pump();
}

double paneWidth(WidgetTester tester, String name) =>
    tester.getSize(key(name)).width;

void main() {
  late AppHarness h;
  setUp(() => h = AppHarness());

  group('布局断点', () {
    testWidgets('≥900：题目 42% / 草稿 58%，并排', (tester) async {
      await open(tester, h);

      final left = tester.getRect(key('split.primary'));
      final right = tester.getRect(key('split.secondary'));
      expect(left.top, right.top);
      expect(left.right, lessThanOrEqualTo(right.left));
      final usable = tabletLandscape.width - 24;
      expect(left.width / usable, closeTo(0.42, 0.005));
      expect(key('solve.questionPane'), findsOneWidget);
      expect(key('solve.scratchPane'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('分隔条可以拖动，范围限制在 35%–60%', (tester) async {
      await open(tester, h);
      final usable = tabletLandscape.width - 24;
      double fraction() => paneWidth(tester, 'split.primary') / usable;

      await tester.drag(key('split.divider'), const Offset(-900, 0));
      await tester.pump();
      expect(fraction(), closeTo(AdaptiveSplit.minFraction, 0.005));

      await tester.drag(key('split.divider'), const Offset(1400, 0));
      await tester.pump();
      expect(fraction(), closeTo(AdaptiveSplit.maxFraction, 0.005));

      await tester.drag(key('split.divider'), const Offset(-200, 0));
      await tester.pump();
      expect(fraction(), inInclusiveRange(0.35, 0.60));
      await teardownTree(tester);
    });

    testWidgets('键盘左右键微调分隔条', (tester) async {
      await open(tester, h);
      final before = paneWidth(tester, 'split.primary');
      await tester.tap(key('split.divider'));
      await tester.sendKeyEvent(LogicalKeyboardKey.arrowRight);
      await tester.pump();
      expect(paneWidth(tester, 'split.primary'), greaterThan(before));
      await teardownTree(tester);
    });

    testWidgets('600–899 横屏：仍然并排，但分隔条不能拖', (tester) async {
      await open(tester, h, size: mediumLandscape);

      expect(
        tester.getRect(key('split.primary')).top,
        tester.getRect(key('split.secondary')).top,
      );
      final before = paneWidth(tester, 'split.primary');
      await tester.drag(
        key('split.divider'),
        const Offset(-200, 0),
        warnIfMissed: false,
      );
      await tester.pump();
      expect(paneWidth(tester, 'split.primary'), before);
      await teardownTree(tester);
    });

    testWidgets('600–899 竖屏：上下排列', (tester) async {
      await open(tester, h, size: const Size(700, 1000));

      final top = tester.getRect(key('split.primary'));
      final bottom = tester.getRect(key('split.secondary'));
      expect(top.bottom, lessThanOrEqualTo(bottom.top));
      expect(top.width, bottom.width);
      await teardownTree(tester);
    });

    testWidgets('<600：单栏，底部切换"题目/草稿"，切换时草稿不丢', (tester) async {
      await open(tester, h, size: phone);
      expect(key('split.tabs'), findsOneWidget);

      await tester.tap(find.text('草稿'));
      await settle(tester, frames: 2);
      final gesture = await tester.startGesture(
        const Offset(200, 300),
        kind: PointerDeviceKind.stylus,
      );
      await gesture.moveBy(const Offset(60, 40));
      await gesture.up();
      await settle(tester, frames: 2);
      expect(
        tester.widget<IconButton>(key('ink.undo')).onPressed,
        isNotNull,
        reason: '画了一笔',
      );

      await tester.tap(find.text('题目'));
      await settle(tester, frames: 2);
      await tester.tap(find.text('草稿'));
      await settle(tester, frames: 2);
      expect(
        tester.widget<IconButton>(key('ink.undo')).onPressed,
        isNotNull,
        reason: '切换之后笔迹还在',
      );
      await teardownTree(tester);
    });

    for (final size in [
      tabletLandscape,
      tabletPortrait,
      mediumLandscape,
      phone,
    ]) {
      testWidgets(
        '字体放大 1.5 倍不溢出：${size.width.toInt()}×${size.height.toInt()}',
        (tester) async {
          await open(tester, h, size: size, textScale: 1.5);
          await tester.tap(key('option.B'));
          await settle(tester, frames: 3);
          expect(tester.takeException(), isNull);
          await teardownTree(tester);
        },
      );
    }

    testWidgets('深色主题能正常显示', (tester) async {
      await open(tester, h, theme: AppTheme.dark());
      expect(find.textContaining('二次函数'), findsWidgets);
      expect(tester.takeException(), isNull);
      await teardownTree(tester);
    });
  });

  group('作答', () {
    testWidgets('顶栏显示学科、题型和保存状态；不选就不能提交', (tester) async {
      await open(tester, h);

      expect(find.textContaining('数学 · 单选题 · 难度 2'), findsOneWidget);
      expect(
        find.descendant(
          of: key('solve.saveStatus'),
          matching: find.text('已保存 · 已同步'),
        ),
        findsOneWidget,
      );
      expect(
        tester.widget<FilledButton>(key('action.submit')).onPressed,
        isNull,
      );
      await teardownTree(tester);
    });

    testWidgets('题干里的公式能渲染，来源标明是自编工程样题', (tester) async {
      await open(tester, h);
      expect(find.textContaining('自编工程样题'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await teardownTree(tester);
    });

    testWidgets('选一个选项后可以提交；答错后看到判定和下一步', (tester) async {
      await open(tester, h);

      await tester.tap(key('option.A'));
      await settle(tester, frames: 2);
      expect(
        tester.widget<FilledButton>(key('action.submit')).onPressed,
        isNotNull,
      );

      await tester.tap(key('action.submit'));
      await settle(tester);

      expect(find.text('这次没答对'), findsOneWidget);
      expect(find.text('这是练习反馈，不是官方阅卷分数。'), findsOneWidget);
      expect(key('action.standard'), findsOneWidget);
      expect(key('action.retry'), findsOneWidget);
      expect(key('action.understood'), findsOneWidget);
      expect(key('action.submit'), findsNothing);
      await teardownTree(tester);
    });

    testWidgets('提交之后答案区变成只读', (tester) async {
      await open(tester, h);
      await choose(tester, 'A');
      await tester.tap(key('action.submit'));
      await settle(tester);

      expect(find.text('你提交的答案'), findsOneWidget);
      final tile = tester.widget<InkWell>(key('option.B'));
      expect(tile.onTap, isNull);
      await teardownTree(tester);
    });

    testWidgets('判不出来：显示"待确认"，并说明不计入正确率', (tester) async {
      h.backend.submitFixture = 'submit_uncertain';
      await open(tester, h);
      await choose(tester, 'A');
      await tester.tap(key('action.submit'));
      await settle(tester);

      expect(find.text('待确认'), findsOneWidget);
      expect(find.text('这次不算对，也不算错，不会计入正确率。'), findsOneWidget);
      expect(find.text('答对了'), findsNothing);
      expect(find.text('这次没答对'), findsNothing);
      await teardownTree(tester);
    });

    testWidgets('答对了：显示"答对了"', (tester) async {
      h.backend.submitFixture = 'submit_correct';
      await open(tester, h);
      await choose(tester, 'B');
      await tester.tap(key('action.submit'));
      await settle(tester);
      expect(find.text('答对了'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('再试一次：新建作答，答案清空，回到作答状态', (tester) async {
      await open(tester, h);
      await choose(tester, 'A');
      await tester.tap(key('action.submit'));
      await settle(tester);

      await tester.tap(key('action.retry'));
      await settle(tester);

      expect(key('action.submit'), findsOneWidget);
      expect(
        tester.widget<FilledButton>(key('action.submit')).onPressed,
        isNull,
      );
      expect(h.backend.attemptsCreated, 2);
      await teardownTree(tester);
    });
  });

  group('提示与解析', () {
    testWidgets('给点提示：每次一层，按钮上显示进度', (tester) async {
      await open(tester, h);
      expect(find.text('给点提示（0/3）'), findsOneWidget);

      await tester.tap(key('action.hint'));
      await settle(tester);

      expect(find.textContaining('提示 第 1/3 层'), findsOneWidget);
      expect(find.text('给点提示（1/3）'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('提交前"我想直接看解析"：先确认；取消则什么都不泄露', (tester) async {
      await open(tester, h);

      await tester.tap(key('action.giveUp'));
      await settle(tester, frames: 3);
      expect(find.text('现在就看解析吗？'), findsOneWidget);
      expect(find.textContaining('不再算“独立作答”'), findsOneWidget);

      await tester.tap(key('dialog.giveUp.cancel'));
      await settle(tester, frames: 3);
      expect(find.text('常规解法'), findsNothing);
      expect(find.textContaining('答案：'), findsNothing);
      await teardownTree(tester);
    });

    testWidgets('确认之后才显示解析，带逐项分析', (tester) async {
      await open(tester, h);
      await tester.tap(key('action.giveUp'));
      await settle(tester, frames: 3);
      await tester.tap(key('dialog.giveUp.confirm'));
      await settle(tester);

      expect(find.text('常规解法'), findsWidgets);
      expect(find.text('逐项分析'), findsOneWidget);
      expect(find.text('答案：'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('快速解法：显示适用条件和不适用的情形', (tester) async {
      await open(tester, h);
      await choose(tester, 'A');
      await tester.tap(key('action.submit'));
      await settle(tester);

      await tester.tap(key('action.fast'));
      await settle(tester);

      expect(find.text('适用条件'), findsOneWidget);
      expect(find.text('不适用的情形'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('看图理解：图解出现在时间线里，滑块可以拖', (tester) async {
      await open(tester, h);

      await tester.tap(key('action.visual'));
      await settle(tester);

      expect(key('visual.canvas'), findsOneWidget);
      expect(key('visual.slider.a'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('"还是不懂"：换种讲法的内容带来源标注（AI 生成）', (tester) async {
      await open(tester, h);
      await choose(tester, 'A');
      await tester.tap(key('action.submit'));
      await settle(tester);

      await tester.tap(key('action.confused'));
      await settle(tester);

      expect(find.text('换种讲法'), findsOneWidget);
      expect(find.textContaining('AI 生成'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('"我懂了"：给出复测安排并结束这次学习', (tester) async {
      await open(tester, h);
      await choose(tester, 'A');
      await tester.tap(key('action.submit'));
      await settle(tester);

      await tester.tap(key('action.understood'));
      await settle(tester);

      expect(find.textContaining('已经安排了复测'), findsOneWidget);
      expect(key('action.done'), findsOneWidget);
      expect(key('action.retry'), findsNothing);
      await teardownTree(tester);
    });
  });

  group('复测', () {
    testWidgets('提交前没有提示和解析按钮，并说明原因', (tester) async {
      await open(tester, h, origin: 'review', reviewItemId: 'review-item-1');

      expect(find.textContaining('这是间隔复测'), findsOneWidget);
      expect(key('action.hint'), findsNothing);
      expect(key('action.visual'), findsNothing);
      expect(key('action.giveUp'), findsNothing);
      expect(key('action.submit'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('提交之后出现复测结果和解析按钮', (tester) async {
      h.backend.submitFixture = 'submit_correct';
      await open(tester, h, origin: 'review', reviewItemId: 'review-item-1');
      await choose(tester, 'B');
      await tester.tap(key('action.submit'));
      await settle(tester);

      expect(find.text('这次复测通过了'), findsOneWidget);
      expect(key('action.standard'), findsOneWidget);
      await teardownTree(tester);
    });
  });

  group('断网与冲突', () {
    testWidgets('断网：顶栏变成"未同步"，出现重试按钮，草稿照常保存在本机', (tester) async {
      await open(tester, h);
      h.backend.offline = true;

      await tester.tap(key('option.C'));
      await tester.pump(const Duration(seconds: 5));
      await settle(tester);

      expect(
        find.descendant(
          of: key('solve.saveStatus'),
          matching: find.text('已存在本机 · 未同步'),
        ),
        findsOneWidget,
      );
      expect(key('banner.retry'), findsOneWidget);
      expect(h.store.data.keys.any((k) => k.contains('/draft/')), isTrue);

      h.backend.offline = false;
      await tester.tap(key('banner.retry'));
      await settle(tester);
      expect(
        find.descendant(
          of: key('solve.saveStatus'),
          matching: find.text('已保存 · 已同步'),
        ),
        findsOneWidget,
      );
      await teardownTree(tester);
    });

    testWidgets('断网时提交：说明原因，答案还在', (tester) async {
      await open(tester, h);
      await choose(tester, 'C');
      h.backend.offline = true;

      await tester.tap(key('action.submit'));
      await settle(tester);

      expect(find.textContaining('连不上服务'), findsWidgets);
      expect(key('action.submit'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('版本冲突：同时展示两边的内容，选"保留我的"之后恢复', (tester) async {
      await open(tester, h);
      await tester.tap(key('option.A'));
      await tester.pump(const Duration(seconds: 5));
      await settle(tester);
      h.backend
        ..serverRevision = 5
        ..serverAnswer = {
          'selected_options': ['D'],
        };

      await tester.tap(key('option.B'));
      await tester.pump(const Duration(seconds: 5));
      await settle(tester);

      expect(find.text('这份草稿在别处有了更新'), findsOneWidget);
      expect(find.textContaining('你这边：选了 B'), findsOneWidget);
      expect(find.textContaining('云端的：选了 D'), findsOneWidget);
      expect(
        tester.widget<FilledButton>(key('action.submit')).onPressed,
        isNull,
        reason: '有冲突先解决',
      );

      await tester.tap(key('banner.keepLocal'));
      await settle(tester);
      expect(find.text('这份草稿在别处有了更新'), findsNothing);
      expect(h.backend.serverAnswer, {
        'selected_options': ['B'],
      });
      await teardownTree(tester);
    });

    testWidgets('版本冲突：选"用云端的"，本地选项换成云端的', (tester) async {
      await open(tester, h);
      await tester.tap(key('option.A'));
      await tester.pump(const Duration(seconds: 5));
      await settle(tester);
      h.backend
        ..serverRevision = 5
        ..serverAnswer = {
          'selected_options': ['D'],
        };
      await tester.tap(key('option.B'));
      await tester.pump(const Duration(seconds: 5));
      await settle(tester);

      await tester.tap(key('banner.useServer'));
      await settle(tester);

      expect(find.text('这份草稿在别处有了更新'), findsNothing);
      expect(
        find.byIcon(Icons.check_circle),
        findsOneWidget,
        reason: '只有被选中的 D 带对勾',
      );
      await teardownTree(tester);
    });

    testWidgets('登录失效：保留草稿并给出"重新登录"', (tester) async {
      await open(tester, h);
      h.backend.failNext = (401, 'unauthenticated');

      await tester.tap(key('option.C'));
      await tester.pump(const Duration(seconds: 5));
      await settle(tester);

      expect(find.textContaining('登录已经失效'), findsOneWidget);
      expect(key('banner.relogin'), findsOneWidget);
      expect(h.store.data.keys.any((k) => k.contains('/draft/')), isTrue);
      await teardownTree(tester);
    });

    testWidgets('没有网络又没有缓存：显示错误和重试，不白屏', (tester) async {
      final offline = AppHarness();
      offline.backend.offline = true;
      await open(tester, offline);

      expect(find.textContaining('连不上服务'), findsOneWidget);
      expect(find.text('重试'), findsOneWidget);
      await teardownTree(tester);
    });
  });

  group('填空题', () {
    Future<void> openFill(WidgetTester tester) async {
      final fillHarness = AppHarness(
        backend: FakeBackend()
          ..installLearningFlow(questionFixture: 'question_fill'),
      );
      await open(
        tester,
        fillHarness,
        questionId: Fixtures.load().value('question_fill')['id'] as String,
      );
    }

    testWidgets('输入框带单位提示；输入后才能提交', (tester) async {
      await openFill(tester);

      expect(find.text('需要写单位'), findsOneWidget);
      expect(
        tester.widget<FilledButton>(key('action.submit')).onPressed,
        isNull,
      );
      await tester.enterText(key('blank.b1'), '5 m/s²');
      await settle(tester, frames: 2);
      expect(
        tester.widget<FilledButton>(key('action.submit')).onPressed,
        isNotNull,
      );
      await teardownTree(tester);
    });

    testWidgets('符号栏把符号插到光标处，并同步到答案', (tester) async {
      await openFill(tester);
      await tester.enterText(key('blank.b1'), '5');
      await tester.pump();

      await tester.tap(key('symbol.²'));
      await tester.pump();

      expect(tester.widget<TextField>(key('blank.b1')).controller!.text, '5²');
      await teardownTree(tester);
    });

    testWidgets('符号按钮不小于 44×44', (tester) async {
      await openFill(tester);
      for (final symbol in ['√', 'π', '²', '≤', '∞']) {
        final size = tester.getSize(key('symbol.$symbol'));
        expect(size.width, greaterThanOrEqualTo(44), reason: symbol);
        expect(size.height, greaterThanOrEqualTo(44), reason: symbol);
      }
      await teardownTree(tester);
    });
  });

  group('触控目标', () {
    testWidgets('底栏和选项的点击区域不小于 44×44', (tester) async {
      await open(tester, h);
      for (final name in [
        'action.submit',
        'action.hint',
        'action.visual',
        'option.A',
        'option.D',
      ]) {
        final size = tester.getSize(key(name));
        expect(size.width, greaterThanOrEqualTo(44), reason: name);
        expect(size.height, greaterThanOrEqualTo(44), reason: name);
      }
      await teardownTree(tester);
    });
  });

  group('草稿画布', () {
    Future<void> stroke(
      WidgetTester tester, {
      PointerDeviceKind kind = PointerDeviceKind.stylus,
      Offset from = const Offset(900, 300),
    }) async {
      final gesture = await tester.startGesture(from, kind: kind);
      await gesture.moveBy(const Offset(40, 20));
      await gesture.moveBy(const Offset(40, 20));
      await gesture.up();
      await tester.pump();
    }

    testWidgets('手写笔画一笔：撤销键亮起；2 秒后落到本机', (tester) async {
      await open(tester, h);
      expect(tester.widget<IconButton>(key('ink.undo')).onPressed, isNull);

      await stroke(tester);

      expect(tester.widget<IconButton>(key('ink.undo')).onPressed, isNotNull);
      await tester.pump(const Duration(seconds: 3));
      await settle(tester, frames: 3);
      final saved = h.store.data.entries.firstWhere(
        (e) => e.key.contains('/draft/'),
      );
      final json = jsonDecode(saved.value) as Map<String, dynamic>;
      expect(
        ((json['strokes'] as Map)['pages'] as List).first['strokes'],
        isNotEmpty,
      );
      await teardownTree(tester);
    });

    testWidgets('见过手写笔之后，手指不再书写（防手掌误触）', (tester) async {
      await open(tester, h);
      await stroke(tester);
      await tester.tap(key('ink.undo'));
      await tester.pump();
      expect(tester.widget<IconButton>(key('ink.undo')).onPressed, isNull);

      await stroke(tester, kind: PointerDeviceKind.touch);

      expect(
        tester.widget<IconButton>(key('ink.undo')).onPressed,
        isNull,
        reason: '手指的一笔被忽略',
      );
      await teardownTree(tester);
    });

    testWidgets('没用过手写笔时手指可以写；"移动"工具下任何输入都不写', (tester) async {
      await open(tester, h);
      await stroke(tester, kind: PointerDeviceKind.touch);
      expect(tester.widget<IconButton>(key('ink.undo')).onPressed, isNotNull);

      await tester.tap(key('ink.tool.hand'));
      await tester.tap(key('ink.undo'));
      await tester.pump();
      await stroke(tester, kind: PointerDeviceKind.touch);
      expect(tester.widget<IconButton>(key('ink.undo')).onPressed, isNull);
      await teardownTree(tester);
    });

    testWidgets('橡皮擦掉一笔；撤销找回', (tester) async {
      await open(tester, h);
      await stroke(tester);
      await tester.tap(key('ink.tool.eraser'));
      await tester.pump();

      final gesture = await tester.startGesture(
        const Offset(920, 310),
        kind: PointerDeviceKind.stylus,
      );
      await gesture.up();
      await tester.pump();
      await tester.tap(key('ink.undo'));
      await tester.pump();

      expect(
        tester.widget<IconButton>(key('ink.redo')).onPressed,
        isNotNull,
        reason: '撤销了擦除，所以可以重做',
      );
      await teardownTree(tester);
    });

    testWidgets('清空要二次确认；取消不清，确认才清，并且可以撤销', (tester) async {
      await open(tester, h);
      await stroke(tester);

      await tester.tap(key('ink.clear'));
      await settle(tester, frames: 3);
      expect(find.text('清空草稿？'), findsOneWidget);
      await tester.tap(key('ink.clear.cancel'));
      await settle(tester, frames: 3);
      expect(
        tester.widget<IconButton>(key('ink.clear')).onPressed,
        isNotNull,
        reason: '还有笔迹',
      );

      await tester.tap(key('ink.clear'));
      await settle(tester, frames: 3);
      await tester.tap(key('ink.clear.confirm'));
      await settle(tester, frames: 3);
      expect(
        tester.widget<IconButton>(key('ink.clear')).onPressed,
        isNull,
        reason: '清空了',
      );

      await tester.tap(key('ink.undo'));
      await tester.pump();
      expect(
        tester.widget<IconButton>(key('ink.clear')).onPressed,
        isNotNull,
        reason: '撤销找回',
      );
      await teardownTree(tester);
    });

    testWidgets('可以加页，也可以换颜色和粗细', (tester) async {
      await open(tester, h);
      await tester.ensureVisible(key('ink.addPage'));
      await tester.pump();
      await tester.tap(key('ink.addPage'));
      await tester.pump();
      expect(key('ink.page.1'), findsOneWidget);

      await tester.tap(key('ink.color.blue'));
      await tester.tap(key('ink.width.thick'));
      await tester.pump();
      expect(find.byIcon(Icons.check), findsWidgets);
      await teardownTree(tester);
    });

    testWidgets('导出图片：生成 PNG 预览', (tester) async {
      await open(tester, h);
      await stroke(tester);

      await tester.runAsync(() async {
        await tester.tap(key('ink.export'));
        await Future<void>.delayed(const Duration(milliseconds: 600));
      });
      await settle(tester, frames: 4);

      expect(find.text('草稿图片'), findsOneWidget);
      expect(key('ink.export.preview'), findsOneWidget);
      await teardownTree(tester);
    });

    testWidgets('重新打开同一道题：笔迹和答案从本机恢复，不重复开会话', (tester) async {
      await open(tester, h);
      await tester.tap(key('option.C'));
      await stroke(tester);
      await tester.pump(const Duration(seconds: 6));
      await settle(tester);
      await teardownTree(tester);
      final sessions = h.backend.sessionsCreated;

      await tester.pumpWidget(h.solvePage());
      await settle(tester);

      expect(h.backend.sessionsCreated, sessions);
      expect(
        tester.widget<IconButton>(key('ink.undo')).onPressed,
        isNull,
        reason: '恢复出来的内容没有撤销历史',
      );
      expect(
        tester.widget<IconButton>(key('ink.clear')).onPressed,
        isNotNull,
        reason: '但笔迹在',
      );
      expect(
        tester.widget<FilledButton>(key('action.submit')).onPressed,
        isNotNull,
        reason: '选项也恢复了',
      );
      await teardownTree(tester);
    });
  });
}
