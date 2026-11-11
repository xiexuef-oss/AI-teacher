import 'package:tutor_contracts/tutor_contracts.dart';

/// 把任何错误变成能直接给学生看的话。不显示异常类名、堆栈或服务端内部信息。
String describeError(Object error) {
  if (error is ApiException) {
    return switch (error.code) {
      'network_error' => '连不上服务。已经保存在这台设备上的内容不会丢，网络恢复后会继续同步。',
      'unauthenticated' => '登录已经失效，需要重新登录。没有同步的草稿还保存在这台设备上。',
      'not_implemented' => '这个功能还在准备中，暂时用不了。',
      'internal_error' => '服务暂时出了问题，请稍后再试。',
      'invalid_response' => '服务返回了无法识别的内容，请稍后再试。',
      'draft_revision_conflict' => '草稿在别处已经有了更新。',
      'independent_attempt_in_progress' => '还没有提交作答，查看解析需要先确认。',
      'hints_disabled_in_retest' => '复测要求不看提示独立完成，提交之后才能查看。',
      'review_not_due' => '这道题还没有到复测时间。',
      _ => error.message,
    };
  }
  return '出了点问题，请稍后再试。';
}

bool isNetworkError(Object error) => error is ApiException && error.isNetwork;

bool isAuthError(Object error) =>
    error is ApiException && error.statusCode == 401;
