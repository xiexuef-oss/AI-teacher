import 'package:flutter/material.dart' hide DataTable;
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/features/solve/experiment_input.dart';

import 'support/app_harness.dart';
import 'support/fake_backend.dart';

/// 实验题数据表的排版与行名。
///
/// 联调截图里发现两处：作答栏窄的时候，数据表最后一列被横向截住；自查对照里的行名写成"第 1 行"，
/// 其实表里第一列就是"AB"。这里用真实导出的样题（纸带那道）直接测 [ExperimentInput]，不经过整个作答页。
void main() {
  const tableKey = ValueKey('experiment.table.t1');

  List<DataTable> tapeTables() => [
    for (final table
        in (Fixtures.load().value('question_experiment')['content']
                as Map<String, dynamic>)['data_tables']
            as List<dynamic>)
      DataTable.fromJson(table as Map<String, dynamic>),
  ];

  DataTable tableOf(List<String> columns, List<DataTableRow> rows) =>
      DataTable.fromJson({
        'key': 't1',
        'title': '表 1',
        'columns': [
          for (final column in columns)
            {'key': column, 'label': column, 'unit': null},
        ],
        'rows': [for (final row in rows) row.toJson()],
      });

  DataTableRow rowOf({String? label, required List<List<String?>> cells}) =>
      DataTableRow.fromJson({
        'key': 'r1',
        'label': label,
        'cells': [
          for (final cell in cells) {'col': cell[0], 'text': cell[1]},
        ],
      });

  group('experimentRowName：一行叫什么', () {
    test('有行标签就用行标签', () {
      final row = rowOf(
        label: '第 1 组',
        cells: [
          ['seg', 'AB'],
          ['v', null],
        ],
      );
      expect(experimentRowName(tableOf(['seg', 'v'], [row]), row, 0), '第 1 组');
    });

    test('没有行标签：用第一列的文字（例如纸带的 AB）', () {
      final row = rowOf(
        cells: [
          ['seg', 'AB'],
          ['x', '4.00'],
          ['v', null],
        ],
      );
      expect(
        experimentRowName(tableOf(['seg', 'x', 'v'], [row]), row, 0),
        'AB',
      );
    });

    test('行标签是空白也当作没有', () {
      final row = rowOf(
        label: '   ',
        cells: [
          ['seg', 'BC'],
          ['v', null],
        ],
      );
      expect(experimentRowName(tableOf(['seg', 'v'], [row]), row, 1), 'BC');
    });

    test('第一列是留空的格子：写"第 N 行"，N 从 1 数起', () {
      final row = rowOf(
        cells: [
          ['v', null],
          ['x', '4.00'],
        ],
      );
      expect(experimentRowName(tableOf(['v', 'x'], [row]), row, 2), '第 3 行');
    });

    test('第一列的文字是空白：写"第 N 行"', () {
      final row = rowOf(
        cells: [
          ['seg', '  '],
          ['v', null],
        ],
      );
      expect(experimentRowName(tableOf(['seg', 'v'], [row]), row, 0), '第 1 行');
    });

    test('只看第一列：别的列有文字也不拿来当行名', () {
      final row = rowOf(
        cells: [
          ['v', null],
          ['x', '4.00'],
        ],
      );
      expect(
        experimentRowName(tableOf(['v', 'x'], [row]), row, 0),
        isNot('4.00'),
      );
    });
  });

  group('数据表的列宽', () {
    late AppHarness h;

    setUp(() => h = AppHarness());

    /// 把 [ExperimentInput] 放进一个指定宽度的栏里（相当于作答页里窄的题目栏）。
    Future<void> pumpTable(
      WidgetTester tester, {
      required double width,
      double textScale = 1,
    }) async {
      useSize(tester, const Size(1000, 1400));
      await tester.pumpWidget(
        h.page(
          Scaffold(
            body: SingleChildScrollView(
              child: Align(
                alignment: Alignment.topLeft,
                child: SizedBox(
                  width: width,
                  child: ExperimentInput(
                    tables: tapeTables(),
                    subquestions: const [],
                    cells: const {},
                    parts: const {},
                    onCell: (table, row, col, value) {},
                    onPart: (key, value) {},
                  ),
                ),
              ),
            ),
          ),
          textScale: textScale,
        ),
      );
      await settle(tester, frames: 4);
    }

    ScrollableState tableScroll(WidgetTester tester) => tester.state(
      find
          .descendant(
            of: find.byKey(tableKey),
            matching: find.byType(Scrollable),
          )
          .first,
    );

    const blankCells = ['t1.r1.v', 't1.r2.v', 't1.r3.v', 't1.r4.v'];

    testWidgets('栏很窄（330）：表格收进栏里，不用左右滑，最后一列的输入框完整在栏内', (tester) async {
      await pumpTable(tester, width: 330);

      expect(tester.takeException(), isNull);
      expect(
        tableScroll(tester).position.maxScrollExtent,
        0,
        reason: '正常字号下表格应该排得进 330 宽的栏',
      );
      for (final cell in blankCells) {
        final box = tester.getRect(find.byKey(ValueKey('cell.$cell')));
        expect(box.left, greaterThanOrEqualTo(0), reason: cell);
        expect(box.right, lessThanOrEqualTo(330), reason: cell);
      }
      expect(find.textContaining('左右滑动'), findsNothing, reason: '不用滑就不用提示');
      await teardownTree(tester);
    });

    testWidgets('栏很宽（900）：表格撑满栏宽，也没有提示', (tester) async {
      await pumpTable(tester, width: 900);

      final table = tester.getRect(
        find.descendant(of: find.byKey(tableKey), matching: find.byType(Table)),
      );
      expect(table.width, closeTo(900, 1));
      expect(tableScroll(tester).position.maxScrollExtent, 0);
      expect(find.textContaining('左右滑动'), findsNothing);
      await teardownTree(tester);
    });

    testWidgets('字体放大 1.5 倍、栏很窄：表格可以左右滑，并且有一句提示；滑到头之后输入框完整可见', (tester) async {
      await pumpTable(tester, width: 330, textScale: 1.5);

      expect(tester.takeException(), isNull);
      expect(
        tableScroll(tester).position.maxScrollExtent,
        greaterThan(0),
        reason: '放大之后排不下，要能滑',
      );
      expect(find.textContaining('左右滑动'), findsOneWidget);

      await tester.drag(find.byKey(tableKey), const Offset(-800, 0));
      await tester.pump();
      for (final cell in blankCells) {
        final box = tester.getRect(find.byKey(ValueKey('cell.$cell')));
        expect(box.right, lessThanOrEqualTo(330), reason: cell);
        expect(box.left, greaterThanOrEqualTo(0), reason: cell);
      }
      expect(tester.takeException(), isNull);
      await teardownTree(tester);
    });

    testWidgets('读屏标签里是行的名字（AB），不是"第 1 行"', (tester) async {
      final handle = tester.ensureSemantics();
      await pumpTable(tester, width: 330);

      expect(
        find.bySemanticsLabel(RegExp('，AB，.*请填写')),
        findsOneWidget,
        reason: '纸带表第一行的平均速度格',
      );
      expect(find.bySemanticsLabel(RegExp('第 1 行')), findsNothing);
      handle.dispose();
      await teardownTree(tester);
    });
  });
}
