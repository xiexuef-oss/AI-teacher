import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/features/solve/answer_input.dart';

import 'support/fake_backend.dart';

void main() {
  testWidgets(
    'fill field semantics exclude the outside symbol palette and help',
    (tester) async {
      final semantics = tester.ensureSemantics();
      try {
        final question = Question.fromJson(
          Fixtures.load().value('question_fill'),
        );
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: SizedBox(
                width: 440,
                child: Card(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Text('你的答案'),
                      FillInput(
                        blanks: question.content.blanks,
                        values: const {},
                        onChanged: (_, _) {},
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        final nodes = <SemanticsNode>[];
        void collect(SemanticsNode node) {
          if (node.getSemanticsData().flagsCollection.isTextField) {
            nodes.add(node);
          }
          node.visitChildren((child) {
            collect(child);
            return true;
          });
        }

        tester.binding.rootPipelineOwner.visitChildren((owner) {
          final root = owner.semanticsOwner?.rootSemanticsNode;
          if (root != null) collect(root);
        });
        expect(nodes, hasLength(1));
        final node = nodes.single;
        expect(node.getSemanticsData().label, isNot(contains('区间可以写成')));
        expect(
          node.rect.height,
          lessThanOrEqualTo(
            tester.getSize(find.byType(TextField).first).height + 1,
          ),
        );
      } finally {
        semantics.dispose();
      }
    },
  );
}
