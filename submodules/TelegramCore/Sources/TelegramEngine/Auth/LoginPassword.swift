import Foundation
import SwiftSignalKit
import TelegramApi

public enum UpdateLoginPasswordError {
    case invalidCurrentPassword
    case invalidNewPassword
    case generic
}

func _internal_updateLoginPassword(network: Network, currentPassword: String, newPassword: String) -> Signal<Never, UpdateLoginPasswordError> {
    var payload = Data(currentPassword.utf8)
    payload.append(0)
    payload.append(Data(newPassword.utf8))

    let settings = Api.account.PasswordInputSettings.passwordInputSettings(.init(
        flags: 1,
        newAlgo: .passwordKdfAlgoUnknown,
        newPasswordHash: Buffer(data: payload),
        hint: "TZ_LOGIN_PASSWORD_V1",
        email: nil,
        newSecureSettings: nil
    ))
    return network.request(Api.functions.account.updatePasswordSettings(
        password: .inputCheckPasswordEmpty,
        newSettings: settings
    ), automaticFloodWait: false)
    |> mapError { error -> UpdateLoginPasswordError in
        if error.errorDescription == "PASSWORD_HASH_INVALID" {
            return .invalidCurrentPassword
        } else if error.errorDescription == "NEW_SETTINGS_INVALID" {
            return .invalidNewPassword
        } else {
            return .generic
        }
    }
    |> ignoreValues
}
