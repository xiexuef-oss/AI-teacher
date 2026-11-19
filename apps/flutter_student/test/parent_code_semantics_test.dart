import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tutor_contracts/tutor_contracts.dart';
import 'package:tutor_student/features/parent/parent_command_store.dart';
import 'package:tutor_student/features/parent/parent_home_page.dart';

import 'support/app_harness.dart';
import 'support/fake_backend.dart';

void main() {
  testWidgets('pending redeem error keeps input semantics within the field', (
    tester,
  ) async {
    useSize(tester, const Size(1280, 1800));
    final h = AppHarness()..signInAs(role: 'parent');
    await ParentCommandStore(
      h.store,
      FakeBackend.parentUserId,
      'parent',
    ).prepareRedeem(
      const ParentInviteRedeem(code: 'ABCDEFGHJK'),
      key: 'synthetic-redeem',
      activeEpoch: 1,
    );
    final handle = tester.ensureSemantics();
    try {
      await tester.pumpWidget(h.page(const ParentHomePage()));
      await tester.pumpAndSettle();
      final field = find.byKey(const ValueKey('parent.code'));
      await tester.enterText(field, 'KJHGFEDCBA');
      await tester.pump();
      await tester.tap(find.byKey(const ValueKey('parent.link')));
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('parent.retry')), findsOneWidget);
      // A mismatching synthetic code leaves the prepared command and an error.
      expect(find.text('出了点问题，请稍后再试。'), findsOneWidget);
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
      expect(
        nodes.single.rect.height,
        lessThanOrEqualTo(tester.getSize(field).height + 1),
      );
      expect(nodes.single.getSemanticsData().label, '邀请码');
    } finally {
      handle.dispose();
    }
  });
}
