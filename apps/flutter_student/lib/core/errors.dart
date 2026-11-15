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
      'attempt_not_submitted' => '提交之后才能对照要点自查。',
      'self_check_not_applicable' => '这道题不需要对照要点自查。',
      // 不区分是写错、过期还是已经用过：服务端也不区分，免得被人拿来试码
      'invite_invalid' => '邀请码不对，或者已经过期、已经被用过。',
      'already_linked' => '已经绑定着这位学生了，不用再输入邀请码。',
      _ => error.message,
    };
  }
  return '出了点问题，请稍后再试。';
}

bool isNetworkError(Object error) => error is ApiException && error.isNetwork;

bool isAuthError(Object error) =>
    error is ApiException && error.statusCode == 401;

/// 404：资源不存在，或者没有权限看（服务端不区分，防止被人用来探测）。
bool isNotFoundError(Object error) =>
    error is ApiException && error.statusCode == 404;
