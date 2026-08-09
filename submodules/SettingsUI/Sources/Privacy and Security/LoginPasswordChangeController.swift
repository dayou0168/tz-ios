import Foundation
import Display
import SwiftSignalKit
import TelegramCore
import TelegramPresentationData
import ItemListUI
import AccountContext
import AlertUI

private enum LoginPasswordField {
    case current
    case new
    case confirmation
}

private enum LoginPasswordEntryTag: ItemListItemTag {
    case current
    case new
    case confirmation

    func isEqual(to other: ItemListItemTag) -> Bool {
        return (other as? LoginPasswordEntryTag) == self
    }
}

private struct LoginPasswordChangeState: Equatable {
    var current = ""
    var new = ""
    var confirmation = ""
    var saving = false
}

private final class LoginPasswordChangeArguments {
    let update: (LoginPasswordField, String) -> Void
    let save: () -> Void

    init(update: @escaping (LoginPasswordField, String) -> Void, save: @escaping () -> Void) {
        self.update = update
        self.save = save
    }
}

private enum LoginPasswordChangeEntry: ItemListNodeEntry {
    case header(PresentationTheme, String)
    case current(PresentationTheme, String, String)
    case new(PresentationTheme, String, String)
    case confirmation(PresentationTheme, String, String)
    case info(PresentationTheme, String)

    var section: ItemListSectionId { return 0 }

    var stableId: Int32 {
        switch self {
        case .header: return 0
        case .current: return 1
        case .new: return 2
        case .confirmation: return 3
        case .info: return 4
        }
    }

    static func < (lhs: LoginPasswordChangeEntry, rhs: LoginPasswordChangeEntry) -> Bool {
        return lhs.stableId < rhs.stableId
    }

    func item(presentationData: ItemListPresentationData, arguments: Any) -> ListViewItem {
        let arguments = arguments as! LoginPasswordChangeArguments
        switch self {
        case let .header(_, text):
            return ItemListSectionHeaderItem(presentationData: presentationData, text: text, sectionId: self.section)
        case let .current(_, placeholder, value):
            return ItemListSingleLineInputItem(presentationData: presentationData, systemStyle: .glass, title: NSAttributedString(), text: value, placeholder: placeholder, type: .password, returnKeyType: .next, spacing: 0.0, tag: LoginPasswordEntryTag.current, sectionId: self.section, textUpdated: { arguments.update(.current, $0) }, action: {})
        case let .new(_, placeholder, value):
            return ItemListSingleLineInputItem(presentationData: presentationData, systemStyle: .glass, title: NSAttributedString(), text: value, placeholder: placeholder, type: .password, returnKeyType: .next, spacing: 0.0, tag: LoginPasswordEntryTag.new, sectionId: self.section, textUpdated: { arguments.update(.new, $0) }, action: {})
        case let .confirmation(_, placeholder, value):
            return ItemListSingleLineInputItem(presentationData: presentationData, systemStyle: .glass, title: NSAttributedString(), text: value, placeholder: placeholder, type: .password, returnKeyType: .done, spacing: 0.0, tag: LoginPasswordEntryTag.confirmation, sectionId: self.section, textUpdated: { arguments.update(.confirmation, $0) }, action: { arguments.save() })
        case let .info(_, text):
            return ItemListTextItem(presentationData: presentationData, text: .plain(text), sectionId: self.section)
        }
    }
}

private func loginPasswordEntries(presentationData: PresentationData, state: LoginPasswordChangeState) -> [LoginPasswordChangeEntry] {
    return [
        .header(presentationData.theme, presentationData.strings.LoginPassword_Title),
        .current(presentationData.theme, presentationData.strings.TwoStepAuth_EnterPasswordPassword, state.current),
        .new(presentationData.theme, presentationData.strings.FastTwoStepSetup_PasswordPlaceholder, state.new),
        .confirmation(presentationData.theme, presentationData.strings.FastTwoStepSetup_PasswordConfirmationPlaceholder, state.confirmation),
        .info(presentationData.theme, presentationData.strings.LoginPassword_PasswordHelp)
    ]
}

public func loginPasswordChangeController(context: AccountContext) -> ViewController {
    let stateValue = Atomic(value: LoginPasswordChangeState())
    let statePromise = ValuePromise(LoginPasswordChangeState(), ignoreRepeated: true)
    let updateState: ((LoginPasswordChangeState) -> LoginPasswordChangeState) -> Void = { f in
        statePromise.set(stateValue.modify(f))
    }
    let disposable = MetaDisposable()
    var saveImpl: (() -> Void)?
    var presentImpl: ((ViewController) -> Void)?
    var popImpl: (() -> Void)?

    let arguments = LoginPasswordChangeArguments(update: { field, text in
        updateState { state in
            var state = state
            switch field {
            case .current: state.current = text
            case .new: state.new = text
            case .confirmation: state.confirmation = text
            }
            return state
        }
    }, save: {
        saveImpl?()
    })

    saveImpl = {
        let state = stateValue.with { $0 }
        let presentationData = context.sharedContext.currentPresentationData.with { $0 }
        guard !state.current.isEmpty, state.new.count >= 8 else {
            presentImpl?(textAlertController(context: context, title: nil, text: "Enter your current password and a new password of at least 8 characters.", actions: [TextAlertAction(type: .defaultAction, title: presentationData.strings.Common_OK, action: {})]))
            return
        }
        guard state.new == state.confirmation else {
            presentImpl?(textAlertController(context: context, title: nil, text: presentationData.strings.TwoStepAuth_SetupPasswordConfirmFailed, actions: [TextAlertAction(type: .defaultAction, title: presentationData.strings.Common_OK, action: {})]))
            return
        }
        updateState { state in var state = state; state.saving = true; return state }
        disposable.set((context.engine.auth.updateLoginPassword(currentPassword: state.current, newPassword: state.new)
        |> deliverOnMainQueue).startStrict(error: { error in
            updateState { state in var state = state; state.saving = false; return state }
            let text: String
            switch error {
            case .invalidCurrentPassword: text = presentationData.strings.LoginPassword_InvalidPasswordError
            case .invalidNewPassword: text = "The new password must contain at least 8 characters."
            case .generic: text = presentationData.strings.Login_UnknownError
            }
            presentImpl?(textAlertController(context: context, title: nil, text: text, actions: [TextAlertAction(type: .defaultAction, title: presentationData.strings.Common_OK, action: {})]))
        }, completed: {
            popImpl?()
        }))
    }

    let signal = combineLatest(context.sharedContext.presentationData, statePromise.get())
    |> deliverOnMainQueue
    |> map { presentationData, state -> (ItemListControllerState, (ItemListNodeState, Any)) in
        let right = ItemListNavigationButton(content: state.saving ? .none : .icon(.done), style: state.saving ? .activity : .bold, enabled: !state.saving && !state.current.isEmpty && !state.new.isEmpty && !state.confirmation.isEmpty, action: { saveImpl?() })
        let controllerState = ItemListControllerState(presentationData: ItemListPresentationData(presentationData), title: .text(presentationData.strings.TwoStepAuth_ChangePassword), leftNavigationButton: nil, rightNavigationButton: right, backNavigationButton: ItemListBackButton(title: presentationData.strings.Common_Back))
        let listState = ItemListNodeState(presentationData: ItemListPresentationData(presentationData), entries: loginPasswordEntries(presentationData: presentationData, state: state), style: .blocks, focusItemTag: LoginPasswordEntryTag.current, animateChanges: false)
        return (controllerState, (listState, arguments))
    }
    |> afterDisposed { disposable.dispose() }

    let controller = ItemListController(context: context, state: signal)
    presentImpl = { [weak controller] child in controller?.present(child, in: .window(.root)) }
    popImpl = { [weak controller] in controller?.navigationController?.popViewController(animated: true) }
    return controller
}
