###############################################################################
# KMS — asymmetric key for biometric signature verification
# KMS must be activated in the console before this resource can be created.
# If KMS is not activated, the resource will fail; the backend falls back to
# a locally generated key pair when KMS_KEY_ID is empty.
###############################################################################

resource "tencentcloud_kms_key" "verify" {
  alias       = "${var.project_name}-biometric-sv2-key"
  key_usage   = "ASYMMETRIC_SIGN_VERIFY_RSA_2048"
  description = "DCTA biometric signature verification (RSA_PKCS1_SHA_256)"
  is_enabled  = true
}
